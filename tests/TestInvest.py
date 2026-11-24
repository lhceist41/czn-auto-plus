"""Check that Daily's invest step spends only on a go caption read with its counter and Units, and writes what each goal unit is short of.

The screens are the boxes OCR read off the Global client's Combatant List, Details tabs, Promotion, Level Up and node
panels and their result cards, with the account code strings OCR reads at the screen's left edge left out. The OCR files
hold centres only, so every box gets `FakeBox`'s 90 x 30 px: the readers place a box by its centre, and the one check that
looks at a box's extent, what lies under a press, only meets the result cards' caption and `进入`, which sit 0.04 apart.

What the step must never do: press `Obtain by Merging`, `Replenish Materials`, `Obtain through dismantling`, `Promotion
required`, a Promotion Mission caption, `Change`, `Assign Partner`, a merge or recharge dialog's buttons, a tab on a frame that is not
Details, or `进入` on the Return item card; spend for a unit whose name it has not read; spend twice from one reading;
spend under the Units to keep. Each guard's test has a negative control: the guard taken away, the press happens.
"""

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.en import daily, invest  # noqa: E402
from tests.TestDailyMode import LOBBY, POINTS, Daily, Task, run_pass  # noqa: E402

# The Combatant List, Mei Lin's card second, Rei's name read as `Re`.
LIST = (
    ("√", 0.042, 0.043), ("主战员列表", 0.164, 0.044), ("Level", 0.784, 0.046), ("『", 0.851, 0.045), ("N", 0.972, 0.029),
    ("ALL", 0.053, 0.155), ("等级", 0.129, 0.435), ("20", 0.273, 0.471), ("等级", 0.272, 0.436), ("等级", 0.566, 0.434),
    ("Veronica", 0.204, 0.487), ("Mei Lin", 0.354, 0.483), ("20", 0.419, 0.471), ("Selena", 0.501, 0.485), ("Re", 0.659, 0.485),
    ("Mika", 0.799, 0.485), ("Owen", 0.943, 0.485), ("2", 0.415, 0.686), ("Synchronization", 0.053, 0.951),
    ("Growth Guide", 0.717, 0.938), ("Preset", 0.936, 0.938),
)
# Mei Lin's Details, Stats tab, at her cap 20/20.
STATS = (
    ("Details", 0.129, 0.046), ("N", 0.972, 0.029), ("00", 0.800, 0.110), ("Mei Lin", 0.767, 0.164), ("八", 0.736, 0.212),
    ("A", 0.774, 0.211), ("Stats", 0.121, 0.258), ("Lv.20/20", 0.768, 0.260), ("Cards", 0.124, 0.351), ("Stats", 0.753, 0.332),
    ("」", 0.967, 0.334), ("攻击力", 0.759, 0.377), ("316", 0.960, 0.378), ("Partners", 0.133, 0.444), ("防御力", 0.765, 0.425),
    ("78", 0.964, 0.425), ("生命值", 0.758, 0.470), ("224", 0.959, 0.471), ("Save Data", 0.140, 0.538), ("Critical Chance", 0.789, 0.519),
    ("3.0%", 0.955, 0.519), ("Critical Damage", 0.789, 0.567), ("125.0%", 0.947, 0.566), ("Potential", 0.134, 0.631),
    ("Memory Fragments", 0.172, 0.724), ("Ego Manifestation", 0.168, 0.818), ("33200TB", 0.912, 0.818), ("Growth Guide", 0.185, 0.921),
    ("Promotions", 0.861, 0.921),
)


def edited(screen, *changes):
    """Give a screen with some boxes' text replaced, as `(old, new)` pairs, each old text matched whole."""
    replaced = dict(changes)
    return tuple((replaced.get(text, text), x, y) for text, x, y in screen)


def without(screen, *texts):
    """Give a screen with the named boxes left out."""
    return tuple(box for box in screen if box[0] not in texts)


def replaced_at(screen, point, text):
    """Give a screen with the box at one point reading other text, where the same text reads elsewhere too."""
    return tuple((text if (x, y) == point else old, x, y) for old, x, y in screen)


STATS_30 = edited(STATS, ("Lv.20/20", "Lv.30/30"))
STATS_BELOW_CAP = edited(STATS, ("Lv.20/20", "Lv.20/30"), ("Promotions", "Level Up"))
# The Stats tab the tap on Selena's portrait still showed: Mei Lin's.
STATS_NOT_SELENA = STATS
# Mei Lin's Promotion panel at 13/15 blue Manuals: the button offers a merge.
PROMOTION_MERGE = (
    ("Details i", 0.139, 0.044), ("62", 0.715, 0.047), ("□", 0.756, 0.045), ("2370K", 0.836, 0.049), ("N", 0.973, 0.031),
    ("Promotions", 0.852, 0.119), ("Lv.20/20", 0.785, 0.259), ("LV.20/30", 0.922, 0.259), ("攻击力", 0.757, 0.344), ("316 >", 0.905, 0.345),
    ("332", 0.957, 0.345), ("防御力", 0.763, 0.395), ("78 >", 0.909, 0.395), ("84", 0.961, 0.397), ("生命值", 0.757, 0.445),
    ("224 >", 0.904, 0.445), ("228", 0.957, 0.445), ("13/15", 0.759, 0.791), ("70,000", 0.947, 0.842), ("Obtain by Merging", 0.860, 0.920),
)
# The same panel at 8/15, offering to replenish; then at 15/15, ready.
PROMOTION_REPLENISH = edited(PROMOTION_MERGE, ("13/15", "8/15"), ("2370K", "2356K"), ("Obtain by Merging", "Replenish Materials"))
PROMOTION_READY = (("√", 0.042, 0.044),) + edited(PROMOTION_MERGE, ("13/15", "15/15"), ("2370K", "2656K"), ("Obtain by Merging", "Promotions"))
# The promotion's result card, then the Level Up panel the game opens next, before and after Auto Register.
PROMOTED = (
    ("Promotions", 0.576, 0.348), ("A", 0.816, 0.348), ("Max Level", 0.568, 0.437), ("20", 0.733, 0.437), ("30", 0.840, 0.438),
    ("攻击力", 0.557, 0.498), ("316", 0.736, 0.498), ("332", 0.834, 0.498), ("防御力", 0.562, 0.560), ("78", 0.733, 0.560), ("84", 0.838, 0.560),
    ("生命值", 0.556, 0.622), ("224", 0.738, 0.621), (">", 0.795, 0.621), ("228", 0.834, 0.620), ("V", 0.499, 0.894),
    ("点击屏幕关闭窗口", 0.501, 0.938),
)
LEVEL_PANEL = (
    ("Details ?", 0.139, 0.045), ("□", 0.755, 0.044), ("2586K", 0.838, 0.048), ("N", 0.973, 0.031), ("Level Up", 0.851, 0.119),
    ("LV.20", 0.751, 0.206), ("0/1500", 0.953, 0.214), ("攻击力", 0.757, 0.294), ("332", 0.956, 0.293), ("防御力", 0.762, 0.343),
    ("84", 0.960, 0.344), ("生命值", 0.756, 0.394), ("228", 0.957, 0.394), ("0/648", 0.754, 0.718), ("0/229", 0.819, 0.718),
    ("0/50", 0.882, 0.718), ("0", 0.967, 0.769), ("Auto Register", 0.852, 0.835), ("Level Up", 0.859, 0.922),
)
LEVEL_REGISTERED = (
    ("√", 0.042, 0.044), ("Details i", 0.139, 0.044), ("□", 0.755, 0.044), ("2586K", 0.837, 0.049), ("N", 0.973, 0.031),
    ("Level Up", 0.851, 0.120), ("Lv.20+10", 0.768, 0.206), ("+434000/1500", 0.921, 0.214), ("攻击力", 0.757, 0.294), ("332", 0.897, 0.294),
    ("371", 0.956, 0.295), ("防御力", 0.763, 0.344), ("84 >", 0.908, 0.344), ("98", 0.962, 0.345), ("生命值", 0.757, 0.394),
    ("228 >", 0.905, 0.394), ("273", 0.957, 0.395), ("0/648", 0.755, 0.717), ("0/229", 0.819, 0.718), ("22/50", 0.882, 0.718),
    ("□", 0.745, 0.769), ("13,020", 0.948, 0.768), ("Auto Register", 0.852, 0.837), ("Level Up", 0.859, 0.920),
)
# Mei Lin's Level Up panel after Auto Register on a day the account held under a million Units, written whole.
LEVEL_PLAIN_UNITS = (
    ("√", 0.042, 0.044), ("Details i", 0.139, 0.044), ("□", 0.755, 0.044), ("888,680", 0.831, 0.049), ("Level Up", 0.851, 0.119),
    ("Lv.1+9", 0.756, 0.208), ("+28000/100", 0.931, 0.215), ("攻击力", 0.757, 0.294), ("160", 0.899, 0.294), ("195", 0.959, 0.294),
    ("防御力", 0.763, 0.344), ("45 >", 0.908, 0.344), ("58", 0.961, 0.345), ("生命值", 0.757, 0.394), ("90 >", 0.909, 0.394), ("131", 0.957, 0.394),
    ("0/15", 0.755, 0.718), ("6/96", 0.819, 0.718), ("0/0", 0.882, 0.718), ("□", 0.744, 0.768), ("840", 0.958, 0.768),
    ("Auto Register", 0.852, 0.836), ("Level Up", 0.859, 0.922),
)
# A Partner's Level Up panel under a tutorial's speech line: the corner reads the line's `Space`.
TUTORIAL_OVER_LEVEL = (
    ("Growth?", 0.128, 0.045), ("1910K", 0.839, 0.049), ("N", 0.973, 0.030), ("Level Up", 0.851, 0.120), ("Lv.1", 0.746, 0.206),
    ("0/100", 0.958, 0.216), ("View Details", 0.078, 0.258), ("攻击力", 0.757, 0.295), ("+13", 0.958, 0.295), ("Level Up", 0.063, 0.351),
    ("防御力", 0.762, 0.344), ("+0", 0.961, 0.344), ("ealth", 0.764, 0.394), ("+0", 0.961, 0.395), ("Ego Mal", 0.060, 0.446),
    ("Douglas", 0.133, 0.755), ("0/312", 0.754, 0.717), ("0/125", 0.819, 0.718), ("0/0", 0.882, 0.718), ("0", 0.968, 0.769),
    ("Huh? There's no combatant available? That can't be!", 0.323, 0.834), ("Auto Register", 0.852, 0.838), ("Space", 0.935, 0.912),
)
LEVELLED = (
    ("Level Up", 0.561, 0.350), ("攻击力", 0.556, 0.438), ("332", 0.738, 0.436), ("371", 0.833, 0.438), ("防御力", 0.562, 0.498),
    ("84", 0.733, 0.499), (">", 0.796, 0.498), ("98", 0.839, 0.498), ("生命值", 0.556, 0.561), ("228", 0.738, 0.560), ("273", 0.833, 0.561),
    ("点击屏幕关闭窗口", 0.500, 0.938),
)
RETURN_ITEM = (("Return item", 0.501, 0.378), ("点击屏幕关闭窗口", 0.501, 0.935), ("进入", 0.500, 0.978))
# The panel once Mei Lin is at 30/30: the next Promotion needs 0/32 Manuals and a Promotion Mission.
MISSION = (
    ("Details ?", 0.139, 0.045), ("62", 0.715, 0.047), ("□", 0.756, 0.045), ("2573K", 0.836, 0.049), ("N", 0.973, 0.031),
    ("Promotions", 0.852, 0.119), ("∠A\\", 0.947, 0.201), ("Lv.30/30", 0.785, 0.259), ("Lv.30/40", 0.921, 0.258), ("攻击力", 0.757, 0.344),
    ("371 >", 0.904, 0.345), ("387", 0.956, 0.345), ("防御力", 0.763, 0.394), ("98 >", 0.909, 0.396), ("104", 0.958, 0.396),
    ("生命值", 0.757, 0.445), ("273 >", 0.905, 0.445), ("277", 0.956, 0.445), ("0/32", 0.758, 0.791), ("150,000", 0.944, 0.842),
    ("Clear the Promotion Mission [Veteran Captain]", 0.852, 0.920),
)
# `Obtain by Merging`'s dialog and its Items Obtained: never reached by the step, read here only to show nothing is pressed.
MERGE_DIALOG = (
    ("Confirm Merge", 0.501, 0.286), ("Would you like to use the above materials to gain 2 Advanced Striker Manual so that this option can be", 0.499, 0.568),
    ("70/6", 0.417, 0.537), ("13/2", 0.586, 0.536), ("enabled?", 0.501, 0.606), ("取消", 0.347, 0.710), ("③Merge", 0.562, 0.710), ("2,000", 0.769, 0.709),
)
# Rosaria's Promotion panel under `Replenish Materials`' dialog: OCR reads only the dialog.
REPLENISH_DIALOG = (
    ("Replenish Materials", 0.501, 0.279), ("37/3", 0.420, 0.510), ("3", 0.589, 0.509),
    ("Would you like to proceed by using Universal Support Certificate to make up for insufficient materials?", 0.501, 0.575),
    ("The amount of Universal Support Certificate consumed varies depending on the grade of the item being replenished.", 0.501, 0.618),
    ("取消", 0.362, 0.717), ("确认", 0.650, 0.716),
)
ROSARIA_PROMOTION = (
    ("Growth i", 0.128, 0.043), ("37", 0.715, 0.048), ("1888K", 0.839, 0.049), ("Promotions", 0.852, 0.119), ("AAAAA", 0.782, 0.201),
    ("AAAAA", 0.922, 0.200), ("View Details", 0.078, 0.257), ("Lv.10/10", 0.785, 0.259), ("LV.10/20", 0.921, 0.259), ("Level Up", 0.064, 0.351),
    ("攻击力", 0.757, 0.344), ("+28 >", 0.904, 0.344), ("+29", 0.957, 0.344), ("防御力", 0.763, 0.394), ("+0 >", 0.909, 0.395),
    ("+1", 0.960, 0.396), ("Ego Manifestation", 0.098, 0.445), ("生命值", 0.756, 0.445), ("+10 >", 0.905, 0.445), ("+15", 0.957, 0.446),
    ("3/6", 0.758, 0.792), ("12,000", 0.948, 0.841), ("公", 0.747, 0.921), ("Replenish Materials", 0.859, 0.920),
)
# Mei Lin's Partners tab: Marianne at 10/10.
PARTNERS = (
    ("Details", 0.139, 0.045), ("2", 0.791, 0.048), ("N", 0.973, 0.030), ("Marianne", 0.807, 0.117), ("日", 0.966, 0.116),
    ("AAAA", 0.766, 0.170), ("Lv.10/10", 0.766, 0.216), ("In Formation", 0.903, 0.219), ("Stats", 0.121, 0.258), ("Check Stats", 0.781, 0.296),
    ("Cards", 0.124, 0.350), ("D", 0.089, 0.443), ("Partners", 0.131, 0.444), ("Lv.1", 0.752, 0.451), ("Lv.1", 0.824, 0.453),
    ("Lv.1", 0.889, 0.452), ("Lv.1", 0.952, 0.452), ("Save Data", 0.139, 0.537), ("Eyes on the Target Lv. 1", 0.851, 0.505), ("Q", 0.757, 0.540),
    ("Partner Passives", 0.822, 0.540), ("XStriker Additional Effect", 0.817, 0.588), ("く", 0.965, 0.587), ("Potential", 0.134, 0.629),
    ("Increase the assigned Combatant's", 0.846, 0.648), ("Attack by 16%.", 0.781, 0.676), ("Ego Manifestation", 0.168, 0.817),
    ("Growth Guide", 0.184, 0.921), ("强化", 0.804, 0.924), ("Change", 0.938, 0.925),
)
# The same tab with `强化` and `Change` read as one box.
PARTNERS_MERGED = tuple(box for box in PARTNERS if box[0] not in ("强化", "Change")) + (("强化 Change", 0.871, 0.924),)
# The Partners tab of two Combatants with no Partner, Rei's and Owen's.
NO_PARTNER = (
    ("Details i", 0.139, 0.044), ("2介", 0.849, 0.049), ("Stats", 0.120, 0.257), ("Cards", 0.124, 0.351), ("Partners", 0.133, 0.444),
    ("Save Data", 0.140, 0.538), ("Assign Partner", 0.557, 0.550), ("Potential", 0.134, 0.631), ("Ego Manifestation", 0.168, 0.726),
    ("Growth Guide", 0.184, 0.922),
)
OWEN_NO_PARTNER = (
    ("Detailsi", 0.139, 0.046), ("2", 0.783, 0.049), ("企", 0.899, 0.049), ("N", 0.973, 0.031), ("Stats", 0.121, 0.256), ("Cards", 0.124, 0.351),
    ("Partners", 0.133, 0.444), ("Save Data", 0.139, 0.538), ("Assign Partner", 0.557, 0.550), ("Potential", 0.134, 0.631),
    ("Ego Manifestation", 0.168, 0.726), ("Growth Guide", 0.185, 0.922),
)
# Marianne's Promotion panel: short of certificates, then ready; her result card; her Level Up panel before and after
# Auto Register, which reads `Level Up` as a left tab too; its cards; and the panel at 20/20, its mission caption garbled.
PARTNER_SHORT = (
    ("Growth i", 0.128, 0.045), ("37", 0.715, 0.048), ("2329K", 0.838, 0.049), ("N", 0.973, 0.031), ("Promotions", 0.852, 0.119),
    ("AAAA", 0.782, 0.201), ("AAAAA", 0.922, 0.200), ("View Details", 0.078, 0.257), ("Lv.10/10", 0.785, 0.258), ("LV.10/20", 0.921, 0.259),
    ("Level Up", 0.064, 0.351), ("攻击力", 0.757, 0.344), ("+45 >", 0.904, 0.344), ("+47", 0.957, 0.345), ("防御力", 0.763, 0.394),
    ("+0 >", 0.909, 0.395), ("+1", 0.960, 0.396), ("Ego Manifestation", 0.098, 0.443), ("生命值", 0.756, 0.445), ("+19 >", 0.905, 0.445),
    ("+24", 0.957, 0.445), ("0/6", 0.758, 0.791), ("12,000", 0.948, 0.841), ("公", 0.746, 0.921), ("Obtain through dismanting", 0.860, 0.920),
)
PARTNER_READY = edited(without(PARTNER_SHORT, "公"), ("2329K", "2334K"), ("0/6", "15/6"), ("Obtain through dismanting", "Promotions"))
PARTNER_PROMOTED = (
    ("Promotions", 0.576, 0.348), ("Max Level", 0.568, 0.437), ("10", 0.732, 0.436), ("20", 0.839, 0.438), ("攻击力", 0.557, 0.499),
    ("+45", 0.738, 0.498), (">", 0.796, 0.498), ("+47", 0.833, 0.498), ("点击屏幕关闭窗口", 0.500, 0.938),
)
PARTNER_LEVEL = (
    ("Growth i", 0.129, 0.045), ("□", 0.756, 0.044), ("2322K", 0.838, 0.048), ("N", 0.972, 0.030), ("Level Up", 0.851, 0.120),
    ("Lv. 10", 0.750, 0.206), ("View Details", 0.078, 0.257), ("0/500", 0.958, 0.215), ("攻击力", 0.757, 0.294), ("+47", 0.957, 0.293),
    ("5", 0.019, 0.348), ("Level Up", 0.064, 0.351), ("防御力", 0.763, 0.343), ("+1", 0.960, 0.344), ("生命值", 0.756, 0.392),
    ("+24", 0.956, 0.395), ("Ego Manifestation", 0.097, 0.443), ("0/332", 0.754, 0.717), ("0/167", 0.819, 0.718), ("0/0", 0.882, 0.718),
    ("□", 0.744, 0.769), ("Auto Register", 0.852, 0.835), ("Level Up", 0.859, 0.920),
)
PARTNER_REGISTERED = (
    ("Growth i", 0.128, 0.043), ("2322K", 0.837, 0.048), ("N", 0.973, 0.031), ("Level Up", 0.851, 0.119), ("Lv.10+10", 0.768, 0.206),
    ("+64000/500", 0.930, 0.215), ("View Details", 0.078, 0.257), ("攻击力", 0.757, 0.294), ("+47 >", 0.904, 0.294), ("+67", 0.957, 0.295),
    ("Level Up", 0.064, 0.351), ("防御力", 0.763, 0.343), ("+1", 0.960, 0.344), ("生命值", 0.756, 0.394), ("+24 >", 0.904, 0.394),
    ("+44", 0.957, 0.394), ("Ego Manifestation", 0.098, 0.444), ("0/332", 0.755, 0.717), ("13/167", 0.820, 0.718), ("0/0", 0.882, 0.718),
    ("□", 0.744, 0.769), ("1,920", 0.953, 0.768), ("Auto Register", 0.852, 0.836), ("Level Up", 0.859, 0.922),
)
PARTNER_LEVELLED = (("Level Up", 0.561, 0.350), ("攻击力", 0.556, 0.438), ("+47", 0.738, 0.437), ("+67", 0.833, 0.438), ("点击屏幕关闭窗口", 0.500, 0.938))
PARTNER_RETURN = (("Return item", 0.501, 0.378), ("V", 0.500, 0.887), ("点击屏幕关闭窗口", 0.501, 0.935), ("进入", 0.500, 0.978))
PARTNER_MISSION = (
    ("Growth i", 0.128, 0.045), ("37", 0.715, 0.048), ("2320K", 0.838, 0.048), ("N", 0.973, 0.031), ("Promotions", 0.852, 0.119),
    ("AAAA", 0.922, 0.200), ("View Details", 0.078, 0.257), ("LV.20/20", 0.785, 0.259), ("LV.20/30", 0.922, 0.260), ("Level Up", 0.064, 0.351),
    ("攻击力", 0.757, 0.344), ("+67 >", 0.904, 0.344), ("+69", 0.957, 0.345), ("防御力", 0.763, 0.394), ("+1 >", 0.909, 0.396),
    ("+2", 0.961, 0.395), ("Ego Manifestation", 0.098, 0.444), ("生命值", 0.756, 0.445), ("+44 >", 0.905, 0.445), ("+49", 0.957, 0.445),
    ("8/12", 0.759, 0.791), ("□", 0.744, 0.842), ("28,000", 0.947, 0.841), ("Clear thePtinissioIteepn]", 0.852, 0.919),
)
# Mei Lin's Potential map, node 02 at 5/10.
MAP = (
    ("Details i", 0.139, 0.045), ("2企", 0.843, 0.048), ("N", 0.973, 0.031), ("品-", 0.132, 0.194), ("Stats", 0.120, 0.258),
    ("Cards", 0.124, 0.351), ("Partners", 0.132, 0.444), ("0/10", 0.411, 0.479), ("0/5", 0.545, 0.482), ("0/5", 0.683, 0.453),
    ("Save Data", 0.140, 0.538), ("Potential", 0.133, 0.630), ("0/10", 0.427, 0.679), ("Memory Fragments", 0.173, 0.724),
    ("03-1", 0.522, 0.744), ("Ego Manifestation", 0.170, 0.815), ("Growth Guide", 0.184, 0.922), ("$", 0.403, 0.907), ("5/10", 0.440, 0.887),
)
# Node 01's panel before the unit's Promotion, and with the Promotion made.
NODE_01_GATED = (
    ("Potential i", 0.134, 0.043), ("433", 0.711, 0.048), ("□", 0.756, 0.046), ("1911K", 0.840, 0.048), ("N", 0.973, 0.031),
    ("Combatant Epiphany", 0.852, 0.120), ("日", 0.735, 0.352), ("Epiphany Bonus", 0.853, 0.354), ("er", 0.192, 0.433),
    ("When entering Chaos, obtain 1", 0.837, 0.415), ("0/10", 0.191, 0.478), ("0/5", 0.461, 0.453), ("random Rare Card with an", 0.820, 0.449),
    ("0/5", 0.324, 0.482), ("activated Epiphany.", 0.798, 0.481), ("Inactive potential.", 0.852, 0.625), ("0/10", 0.206, 0.679),
    ("03-1", 0.305, 0.742), ("14/8", 0.758, 0.791), ("0/10", 0.221, 0.887), ("□", 0.744, 0.841), ("10,000", 0.947, 0.842),
    ("Promotion required", 0.853, 0.921),
)
NODE_01_READY = without(NODE_01_GATED, "Promotion required") + (("Activate", 0.860, 0.920),)
# Node 01's panel once active, Mei Lin's and Selena's: no counter, cost or button.
NODE_01_DONE = (
    ("√", 0.042, 0.044), ("Potential", 0.134, 0.044), ("401", 0.711, 0.048), ("□", 0.756, 0.046), ("1953K", 0.839, 0.049), ("N", 0.973, 0.031),
    ("Combatant Epiphany", 0.852, 0.120), ("Epiphany Bonus", 0.853, 0.355), ("When entering Chaos, obtain 1", 0.838, 0.417), ("0/10", 0.190, 0.479),
    ("0/5", 0.461, 0.453), ("random Rare Card with an", 0.821, 0.449), ("0/5", 0.324, 0.482), ("activated Epiphany.", 0.799, 0.482),
    ("0/10", 0.206, 0.679), ("0/10", 0.221, 0.887),
)
SELENA_NODE_01_DONE = (
    ("√", 0.042, 0.044), ("Potential", 0.134, 0.046), ("401", 0.711, 0.048), ("1914K", 0.840, 0.049), ("Combatant Epiphany", 0.852, 0.120),
    ("Epiphany Bonus", 0.853, 0.356), ("When entering Chaos, obtain 1", 0.838, 0.417), ("0/10", 0.190, 0.480), ("0/5", 0.324, 0.482),
    ("0/5", 0.461, 0.453), ("random Rare Card with an", 0.820, 0.449), ("activated Epiphany.", 0.799, 0.481), ("0/10", 0.206, 0.680),
    ("03-1", 0.300, 0.744), ("0/10", 0.221, 0.888),
)
NODE_CARD = (
    ("Potential", 0.564, 0.347), ("Basic Card Upgrade", 0.598, 0.434), ("Increase Damage, Shield Gain, and Heal Amounts", 0.687, 0.500),
    ("of Basic Cards by4%", 0.597, 0.531), ("V", 0.500, 0.894), ("点击屏幕关闭窗口", 0.500, 0.938),
)
# Node 02's panel at Lv.1 with 14/4 stones, at Lv.2, and at Lv.5 behind the next Promotion with 6/3.
NODE_02 = (
    ("√", 0.042, 0.044), ("Potential", 0.134, 0.044), ("463", 0.710, 0.049), ("2320K", 0.838, 0.048), ("N", 0.973, 0.031),
    ("Upgrade Card", 0.853, 0.122), ("LV.1", 0.853, 0.296), ("Basic Card Upgrade", 0.853, 0.355), ("0/10", 0.190, 0.479), ("0/5", 0.324, 0.482),
    ("Heal Amounts of Basic Cards by", 0.840, 0.448), ("Increase Damage, Shield Gain, and", 0.849, 0.418), ("0/5", 0.461, 0.453), ("2%", 0.746, 0.480),
    ("0/10", 0.205, 0.680), ("03-1", 0.302, 0.743), ("14/4", 0.757, 0.791), ("3,000", 0.950, 0.842), ("1/10", 0.222, 0.888),
    ("Activate", 0.860, 0.920),
)
NODE_02_LV2 = edited(NODE_02, ("LV.1", "Lv.2"), ("14/4", "10/6"), ("2320K", "2317K"), ("1/10", "2/10"))
NODE_02_GATED = edited(NODE_02, ("LV.1", "LV.5"), ("14/4", "6/3"), ("3,000", "12,000"), ("2320K", "2308K"), ("1/10", "5/10"),
                       ("Activate", "Promotion required"))
# The Lobby's menu as it faded in over Details: tab captions and menu entries on one frame.
BLENDED = (
    ("DetailsC", 0.139, 0.046), ("故事", 0.582, 0.092), ("F1", 0.726, 0.062), ("⭐", 0.736, 0.091), ("Event", 0.782, 0.087), ("ESC", 0.961, 0.075),
    ("Act 1- Chapter 2, Episode2", 0.519, 0.128), ("F2", 0.725, 0.137), ("Arkhianon Supply", 0.826, 0.160), ("日", 0.904, 0.159),
    ("Sortie", 0.581, 0.201), ("F3", 0.725, 0.207), ("0/1", 0.064, 0.261), ("Activity", 0.789, 0.232), ("Simulation", 0.571, 0.287),
    ("Unigram", 0.792, 0.305), ("Cards", 0.124, 0.351), ("Chaos", 0.588, 0.376), ("Partners", 0.792, 0.376), ("Partners", 0.132, 0.444),
    ("Awaiting policies 3", 0.551, 0.489), ("Storage", 0.790, 0.452), ("Save Data", 0.141, 0.538), ("Achievement", 0.809, 0.522),
    ("Combatants", 0.565, 0.551), ("Potential", 0.135, 0.631), ("Archive", 0.789, 0.593), ("EVENT", 0.519, 0.639), ("营救", 0.583, 0.639),
    ("Shop", 0.781, 0.666), ("Memory Fragments", 0.176, 0.723), ("Ego Manifestation", 0.168, 0.817), ("Nightmare Carnival", 0.102, 0.930),
    ("End", 0.963, 0.949),
)
# What the step must never press, as captions under a click.
NEVER_TEXTS = ("Obtain by Merging", "Replenish Materials", "Obtain through dismanting", "Promotion required", "Change", "强化 Change",
               "③Merge", "取消", "确认", "进入", "Save Data", "Cards", "Synchronization", "Preset", "Growth Guide", "Ego Manifestation",
               "Clear the Promotion Mission [Veteran Captain]", "Clear thePtinissioIteepn]", "Activated", "View Details", "Assign Partner")
SETTLED = daily.PANEL_SETTLE + 1


class InvestTask(Task):
    """Daily with a goal list, recording the captions under every tap."""

    def __init__(self, goals=("Mei Lin",), floor=daily.UNITS_FLOOR):
        super().__init__()
        self.config = {daily.GOALS_SETTING: list(goals), daily.FLOOR_SETTING: floor}
        self.under = []

    def click(self, x, y, after_sleep=0):
        super().click(x, y, after_sleep)
        self.under.append([box.name for box in daily.boxes_at(self, (x, y))])


class Invest(Daily):
    """Daily on its invest step, every chore before it done, the goal file in a throwaway folder."""

    goals = ("Mei Lin",)

    def setUp(self):
        super().setUp()
        self.task = InvestTask(self.goals)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.goals_file = os.path.join(folder.name, "data", "farm_goals.json")
        patcher = mock.patch.object(invest, "GOALS_FILE", self.goals_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.to_invest()

    def to_invest(self):
        steps = self.state()["steps"]
        for step in steps:
            if step != daily.INVEST:
                steps[step] = daily.DONE
        self.state()["mail"] = "claimed"
        self.state()["claims"]["captain"] = "not listed"
        self.state()["park"]["result"] = "Dream Park is not running"

    def run_screens(self, screens):
        for screen in screens:
            run_pass(self.task.show(screen))
            self.tick()

    def visiting(self, unit="Mei Lin", phase=daily.TO_PROMOTE):
        """Stand on a goal unit's visit, its name read, as the list and its Stats tab leave it."""
        inv = daily.invest_state(self.task)
        daily.invest_goals(self.task)
        inv["index"] = inv["goals"].index(unit)
        visit = inv["visit"] = daily.new_visit(unit, inv["index"])
        visit.update(checked=True, arrived=True, phase=phase, below_cap=False)
        return visit

    def lines(self):
        with open(self.goals_file, encoding="utf-8") as file:
            return json.load(file)

    def assertNeverPressed(self):
        for under in self.task.under:
            for text in NEVER_TEXTS:
                self.assertNotIn(text, under, self.task.under)

    def assertOnlyPressed(self, target):
        """Check there was a tap and every tap was this target, as a back arrow pressed again while its screen still shows."""
        self.assertTrue(self.task.clicks)
        for x, y in self.task.clicks:
            self.assertAlmostEqual(POINTS[target][0], x, delta=0.005, msg=self.task.clicks)
            self.assertAlmostEqual(POINTS[target][1], y, delta=0.005, msg=self.task.clicks)

    def assertPressedTexts(self, *texts):
        """Check each tap landed on a box reading this caption, in order; None for a tap on open screen."""
        self.assertEqual(len(texts), len(self.task.under), self.task.under)
        for under, text in zip(self.task.under, texts):
            if text is None:
                self.assertEqual([], under)
            else:
                self.assertIn(text, under)


class TestReaders(unittest.TestCase):
    """Each screen is read whole, or not at all."""

    def setUp(self):
        self.task = Task()

    def read(self, reader, screen):
        return reader(self.task.show(screen))

    def test_the_stats_tab_reads_its_name_level_and_button(self):
        stats = self.read(invest.stats_screen, STATS)
        self.assertEqual(("Mei Lin", 20, 20, "promotions"), stats[:4])
        self.assertEqual((20, 30, "levelup"), self.read(invest.stats_screen, STATS_BELOW_CAP)[1:4])

    def test_a_stats_tab_missing_any_part_is_no_stats_tab(self):
        """Header, name, level pair, heading and button, each in its region. Negative control: the whole frame reads."""
        self.assertIsNotNone(self.read(invest.stats_screen, STATS))
        for text in ("Details", "Mei Lin", "Lv.20/20", "Promotions"):
            with self.subTest(text=text):
                self.assertIsNone(self.read(invest.stats_screen, without(STATS, text)))
        self.assertIsNone(self.read(invest.stats_screen, tuple(box for box in STATS if box[1:] != (0.753, 0.332))))
        for screen in (PARTNERS, MAP, BLENDED, PROMOTION_MERGE):
            self.assertIsNone(self.read(invest.stats_screen, screen))

    def test_promotion_panels_read_every_number(self):
        panel = self.read(invest.promotion_panel, PROMOTION_MERGE)
        self.assertEqual(("combatant", 20, 20, 30, 13, 15, 70_000, 2_370_000, "obtainbymerging"), panel[:9])
        self.assertEqual(("partner", 20, 20, 30, 8, 12, 28_000, 2_320_000), self.read(invest.promotion_panel, PARTNER_MISSION)[:8])
        self.assertEqual((30, 30, 40, 0, 32, 150_000), self.read(invest.promotion_panel, MISSION)[1:7])

    def test_a_promotion_panel_missing_a_number_is_no_panel(self):
        """The counter, the cost and the Units header each must parse. Negative control: the whole frame reads."""
        self.assertIsNotNone(self.read(invest.promotion_panel, PROMOTION_READY))
        for text in ("15/15", "70,000", "2656K", "Lv.20/20", "LV.20/30", "Promotions"):
            with self.subTest(text=text):
                self.assertIsNone(self.read(invest.promotion_panel, without(PROMOTION_READY, text)))

    def test_the_units_header_reads_thousands_with_k_or_whole_units(self):
        """`2656K`, and under a million `888,680` or plain digits; a million-style or garbled header is no read."""
        self.assertEqual(2_656_000, self.read(invest.units_held, PROMOTION_READY))
        self.assertEqual(888_680, self.read(invest.units_held, LEVEL_PLAIN_UNITS))
        for header, units in (("888680", 888_680), ("2656", 2_656), ("2656k", 2_656_000)):
            with self.subTest(header=header):
                self.assertEqual(units, self.read(invest.units_held, edited(PROMOTION_READY, ("2656K", header))))
        for header in ("2.65M", "2656KK", "26S6K", "2,656K", "88,8680", "888.680"):
            with self.subTest(header=header):
                self.assertIsNone(self.read(invest.units_held, edited(PROMOTION_READY, ("2656K", header))))

    def test_a_header_run_into_its_neighbour_is_no_read(self):
        """`62 2656K` read as one box. Negative control: matched with its space folded out, it would read 622,656,000."""
        merged = edited(without(PROMOTION_READY, "62"), ("2656K", "62 2656K"))
        self.assertIsNone(self.read(invest.units_held, merged))
        self.assertIsNone(self.read(invest.promotion_panel, merged))
        self.assertEqual("622656", invest.UNITS.fullmatch(invest.folded("62 2656K")).group(1))

    def test_an_active_node_reads_as_done_and_a_node_with_a_button_does_not(self):
        """Mei Lin's and Selena's node 01 once active. Negative control: any counter, cost or button makes it no done node."""
        for screen in (NODE_01_DONE, SELENA_NODE_01_DONE):
            self.assertEqual(("epiphanybonus",), tuple(self.read(invest.done_node, screen)))
            self.assertIsNone(self.read(invest.node_panel, screen))
        for screen in (NODE_01_GATED, NODE_01_READY, NODE_02, NODE_02_GATED, MAP, STATS, PROMOTION_READY):
            self.assertIsNone(self.read(invest.done_node, screen))
        for extra in (("14/8", 0.758, 0.791), ("10,000", 0.947, 0.842), ("Activate", 0.860, 0.920)):
            with self.subTest(extra=extra[0]):
                self.assertIsNone(self.read(invest.done_node, NODE_01_DONE + (extra,)))
        self.assertIsNone(self.read(invest.done_node, without(NODE_01_DONE, "When entering Chaos, obtain 1", "random Rare Card with an",
                                                              "activated Epiphany.")))

    def test_a_partners_tab_with_no_partner_reads_as_such(self):
        """Rei's and Owen's tabs. Negative control: a Partner's tab, the Stats tab and the map are not it."""
        for screen in (NO_PARTNER, OWEN_NO_PARTNER):
            self.assertTrue(self.read(invest.no_partner_tab, screen))
            self.assertIsNone(self.read(invest.partners_tab, screen))
        for screen in (PARTNERS, STATS, MAP, BLENDED, without(NO_PARTNER, "Assign Partner")):
            self.assertFalse(self.read(invest.no_partner_tab, screen))

    def test_node_02_reads_full_only_at_its_last_level(self):
        self.assertFalse(self.read(invest.node_02_full, MAP))
        self.assertTrue(self.read(invest.node_02_full, edited(MAP, ("5/10", "10/10"))))
        self.assertFalse(self.read(invest.node_02_full, without(MAP, "5/10")))

    def test_level_panels_read_the_preview_and_the_cost_once_registered(self):
        self.assertEqual(("combatant", 20, 0, 0, 2_586_000, "levelup"), self.read(invest.level_panel, LEVEL_PANEL)[:6])
        self.assertEqual(("combatant", 20, 10, 13_020), self.read(invest.level_panel, LEVEL_REGISTERED)[:4])
        self.assertEqual(("partner", 10, 0, None), self.read(invest.level_panel, PARTNER_LEVEL)[:4])
        self.assertEqual(("partner", 10, 10, 1_920), self.read(invest.level_panel, PARTNER_REGISTERED)[:4])

    def test_a_partner_level_panel_needs_its_title_not_its_left_tab(self):
        """On a Partner's panel `Level Up` reads three times; only the title counts. Negative control: with the title it reads."""
        self.assertIsNotNone(self.read(invest.level_panel, PARTNER_LEVEL))
        self.assertIsNone(self.read(invest.level_panel, tuple(box for box in PARTNER_LEVEL if box[1:] != (0.851, 0.120))))

    def test_the_partners_tab_reads_its_partner_and_a_lone_强化(self):
        partner = self.read(invest.partners_tab, PARTNERS)
        self.assertEqual(("Marianne", 10, 10), partner[:3])
        self.assertEqual("强化", partner.upgrade_box.name)
        self.assertIsNone(self.read(invest.partners_tab, PARTNERS_MERGED).upgrade_box)

    def test_node_panels_read_their_node_counter_and_cost(self):
        self.assertEqual(("basiccardupgrade", 1, 14, 4, 3_000, 2_320_000, "activate"), self.read(invest.node_panel, NODE_02)[:7])
        self.assertEqual(("epiphanybonus", None, 14, 8, 10_000, 1_911_000, "promotionrequired"), self.read(invest.node_panel, NODE_01_GATED)[:7])

    def test_the_potential_map_is_told_from_stats_partners_a_node_panel_and_the_blended_frame(self):
        self.assertTrue(self.read(invest.potential_map, MAP))
        for screen in (STATS, PARTNERS, NODE_02, BLENDED, LIST):
            self.assertFalse(self.read(invest.potential_map, screen))

    def test_result_cards_are_told_by_their_title_and_caption(self):
        cases = ((PROMOTED, invest.PROMOTION), (PARTNER_PROMOTED, invest.PROMOTION), (LEVELLED, invest.LEVEL), (RETURN_ITEM, "return item"),
                 (NODE_CARD, "potential"))
        for screen, kind in cases:
            with self.subTest(kind=kind):
                self.assertEqual(kind, self.read(invest.result_card, screen).kind)
        for screen in (MERGE_DIALOG, REPLENISH_DIALOG, PROMOTION_READY, LEVEL_PANEL, (("Items Obtained", 0.502, 0.377), ("点击屏幕关闭窗口", 0.501, 0.935))):
            self.assertIsNone(self.read(invest.result_card, screen))

    def test_the_combatant_list_finds_a_goal_unit_by_its_whole_name_or_a_lone_start_of_it(self):
        self.task.show(LIST)
        x, y = invest.card_point(self.task, "Mei Lin")
        self.assertAlmostEqual(0.324, x, delta=0.001)
        self.assertEqual(0.33, y)
        self.assertAlmostEqual(0.629, invest.card_point(self.task, "Rei")[0], delta=0.001)
        self.assertIsNone(invest.card_point(self.task, "Tressa"))
        self.assertIsNone(invest.card_point(self.task.show(LIST + (("Re", 0.9, 0.485),)), "Rei"))

    def test_the_stats_name_must_match_whole(self):
        self.assertTrue(invest.same_name("Mei Lin", "Mei Lin"))
        self.assertTrue(invest.same_name("MeiLin", "Mei Lin"))
        for read in ("Re", "Mei", "Selena", ""):
            self.assertFalse(invest.same_name(read, "Rei" if read == "Re" else "Mei Lin"))

    def test_the_refusals_cover_every_never_press_caption(self):
        """A backstop beside the go-word rule."""
        for text in ("Obtain by Merging", "Obtain through dismanting", "Replenish Materials", "Promotion required", "Clear the Promotion Mission [Veteran Captain]",
                     "Change", "Remove", "Dismantle", "Dismantle in Bulk", "Save Data", "Cards", "Synchronization", "Edit Data", "③Merge",
                     "Recharge Aether", "Assign Partner", "View Details", "Ego Manifestation", "Memory Fragments", "Growth Guide", "Preset"):
            with self.subTest(text=text):
                self.assertIsNotNone(invest.refused(text))
        for text in ("Promotions", "Level Up", "Activate", "Auto Register", "强化", "Partners", "Potential", "Stats", "点击屏幕关闭窗口"):
            with self.subTest(text=text):
                self.assertIsNone(invest.refused(text))


class TestGoalList(unittest.TestCase):

    def test_the_goal_list_keeps_known_names_once_in_order_and_names_the_rest(self):
        goals = invest.goal_units(["Mei Lin", "Selena", "Mei Lin", " Rei ", "Meilin", "", "Marianne"])
        self.assertEqual(["Mei Lin", "Selena", "Rei"], goals.units)
        self.assertEqual(["Meilin", "Marianne"], goals.unknown)
        self.assertEqual(([], []), tuple(invest.goal_units(None)))

    def test_every_name_offered_is_one_the_check_knows(self):
        self.assertEqual(set(), set(daily.COMBATANTS) - set(invest.COMBATANT_CLASS))

    def test_each_short_action_names_the_stage_that_drops_it(self):
        self.assertEqual("Combatant Promotion Materials - Striker", invest.stage_for("Mei Lin", invest.PROMOTION, caption="obtainbymerging"))
        self.assertEqual("Combatant Promotion Materials - Controller", invest.stage_for("Rei", invest.PROMOTION))
        self.assertEqual("Partner Promotion Materials - Striker", invest.stage_for("Mei Lin", invest.PARTNER_PROMOTION, "Marianne"))
        self.assertEqual("Potential Materials - Passion", invest.stage_for("Mei Lin", invest.NODE_02, caption="replenishmaterials"))
        self.assertEqual("", invest.stage_for("Mei Lin", invest.PARTNER_PROMOTION, "Somebody"))
        self.assertEqual("", invest.stage_for("Mei Lin", invest.PROMOTION, caption="clearthepromotionmission[veterancaptain]"))
        self.assertEqual("", invest.stage_for("Mei Lin", invest.NODE_02, caption="promotionrequired"))

    def test_a_later_unit_levels_only_while_no_earlier_one_holds_the_materials(self):
        """The hold itself: whoever `end_visit` put in `held` stops every unit listed after it, never one before."""
        units = ["Mei Lin", "Selena", "Mika"]
        self.assertTrue(invest.level_allowed(units, 0, {"Mei Lin"}))
        self.assertFalse(invest.level_allowed(units, 2, {"Mei Lin"}))
        self.assertTrue(invest.level_allowed(units, 2, {"Mika"}))


class TestGoalFile(unittest.TestCase):

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "data", "farm_goals.json")

    def test_the_file_is_json_with_one_short_action_per_line(self):
        lines = [invest.goal_line("Mei Lin", invest.PROMOTION, 13, 15, 70_000, "Obtain by Merging", "Combatant Promotion Materials - Striker", "t"),
                 invest.goal_line("Mei Lin", invest.NODE_02, 6, 3, 12_000, "Promotion required", "", "t")]
        invest.write_goals(lines, self.path)
        text = Path(self.path).read_text(encoding="utf-8")
        self.assertEqual(lines, json.loads(text))
        self.assertEqual(4, len(text.splitlines()))
        self.assertEqual(["unit", "action", "have", "need", "units", "caption", "stage", "read_at"], list(json.loads(text)[0]))

    def test_no_short_action_writes_an_empty_list(self):
        invest.write_goals([], self.path)
        self.assertEqual([], json.loads(Path(self.path).read_text(encoding="utf-8")))

    def test_a_write_that_fails_halfway_leaves_the_old_file_whole(self):
        invest.write_goals([invest.goal_line("Mei Lin", invest.PROMOTION, 1, 2, 3, "c", "s", "t")], self.path)
        before = Path(self.path).read_bytes()
        real_dumps = json.dumps
        calls = []

        def failing(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise OSError("disk full")
            return real_dumps(*args, **kwargs)

        with mock.patch.object(invest.json, "dumps", failing), self.assertRaises(OSError):
            invest.write_goals([invest.goal_line("Selena", invest.PROMOTION, 1, 2, 3, "c", "s", "t")] * 3, self.path)
        self.assertEqual(before, Path(self.path).read_bytes())
        self.assertEqual(["farm_goals.json"], os.listdir(os.path.dirname(self.path)))

    def test_the_negative_control_a_direct_write_would_leave_half_a_file(self):
        """Writing straight into the file, the same failure leaves it cut short: the file beside it is what keeps it whole."""
        invest.write_goals([invest.goal_line("Mei Lin", invest.PROMOTION, 1, 2, 3, "c", "s", "t")], self.path)
        before = Path(self.path).read_bytes()
        with self.assertRaises(OSError), mock.patch.object(invest.json, "dumps", side_effect=OSError("disk full")):
            with open(self.path, "w", encoding="utf-8") as file:
                file.write(invest.json.dumps({}))
        self.assertNotEqual(before, Path(self.path).read_bytes())


class TestShape(unittest.TestCase):

    def test_invest_reads_and_decides_and_never_imports_daily(self):
        """Handlers, targets and limits live in Daily; `invest` cannot import it back."""
        tree = ast.parse((REPO_ROOT / "src" / "en" / "invest.py").read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
        modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertNotIn("daily", imported)
        self.assertNotIn("src.en.daily", modules)
        self.assertNotIn("handle", " ".join(name for name in dir(invest)))

    def test_the_invest_step_runs_last_after_dream_park(self):
        self.assertEqual(["mail", "activity", "achievement", "carnival", "dream_park", "invest"], [step.name for step in daily.STEPS])

    def test_the_two_settings_are_declared_with_a_pick_list_and_a_floor(self):
        task = daily.DailyMode.__new__(daily.DailyMode)
        task.default_config, task.config_type, task.config_description = {}, {}, {}
        with mock.patch.object(daily.TriggerTask, "__init__", lambda self, *args, **kwargs: None):
            daily.DailyMode.__init__(task)
        self.assertEqual([], task.default_config[daily.GOALS_SETTING])
        self.assertEqual(daily.COMBATANTS, task.config_type[daily.GOALS_SETTING]["options_available"])
        self.assertEqual(300_000, task.default_config[daily.FLOOR_SETTING])
        self.assertTrue(task.config_description[daily.GOALS_SETTING] and task.config_description[daily.FLOOR_SETTING])

    def test_the_setting_labels_reach_the_ui_through_both_catalogs(self):
        import polib

        for language in ("en_US", "zh_CN"):
            catalog = polib.pofile(str(REPO_ROOT / "i18n" / language / "LC_MESSAGES" / "ok.po"))
            msgids = {entry.msgid for entry in catalog}
            for label in (daily.GOALS_SETTING, daily.FLOOR_SETTING):
                with self.subTest(language=language, label=label):
                    self.assertIn(label, msgids)


class TestEntry(Invest):

    def test_an_empty_goal_list_finishes_on_the_lobby_and_leaves_no_file(self):
        """The step does nothing and leaves nothing behind. Negative control: with a goal list the Lobby's Combatants is pressed."""
        self.task.config[daily.GOALS_SETTING] = []
        self.run_screens([LOBBY])
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Daily finished")
        self.assertNotIn("Invest", self.task.notifications[0])
        self.assertFalse(os.path.exists(self.goals_file))
        self.task = InvestTask(("Mei Lin",))
        self.to_invest()
        self.run_screens([LOBBY])
        self.assertPressed(daily.INVEST_ENTRY)

    def test_an_empty_goal_list_leaves_an_old_goal_file_as_it_was(self):
        os.makedirs(os.path.dirname(self.goals_file))
        Path(self.goals_file).write_text("[]\n", encoding="utf-8")
        before = os.stat(self.goals_file).st_mtime_ns
        self.task.config[daily.GOALS_SETTING] = []
        self.run_screens([LOBBY])
        self.assertEqual(before, os.stat(self.goals_file).st_mtime_ns)

    def test_names_the_game_does_not_know_are_logged_and_left_out(self):
        self.task.config[daily.GOALS_SETTING] = ["Meilin", "Mei Lin"]
        self.run_screens([LOBBY, LIST])
        self.assertPressed(daily.INVEST_ENTRY, daily.UNIT_CARD)
        self.assertTrue(any("Meilin" in line for line in self.task.logged))

    def test_a_goal_unit_off_the_visible_row_is_skipped_with_a_note(self):
        """The list is never dragged."""
        self.task.config[daily.GOALS_SETTING] = ["Tressa"]
        self.run_screens([LOBBY] + [LIST] * (daily.SETTLE + 1) + [LIST] * 2 + [LOBBY])
        self.assertPressed(daily.INVEST_ENTRY, daily.LIST_LEAVE)
        self.assertEqual([], self.task.swipes)
        self.assertStopped("Tressa: not on the Combatant List's visible row")

    def test_rei_read_as_re_gets_her_card_tapped(self):
        self.task.config[daily.GOALS_SETTING] = ["Rei"]
        self.run_screens([LIST])
        self.assertEqual(1, len(self.task.clicks))
        self.assertAlmostEqual(0.629, self.task.clicks[0][0], delta=0.002)

    def test_nothing_is_pressed_on_an_invest_screen_while_another_step_is_pending(self):
        """Negative control: with the gate taken away, the Stats tab gets its corner pressed."""
        self.state()["steps"]["mail"] = daily.PENDING
        self.visiting()
        for screen in (STATS, PROMOTION_READY, LIST, MAP, NODE_02, PARTNERS):
            run_pass(self.task.show(screen))
        self.assertEqual([], self.task.clicks)
        with mock.patch.object(daily, "invest_active", lambda task: True):
            run_pass(self.task.show(STATS))
        self.assertPressed(daily.OPEN_PROMOTION)


class TestNameCheck(Invest):

    goals = ("Selena", "Mei Lin")

    def test_a_stats_tab_naming_another_unit_presses_only_the_way_out(self):
        """Selena's tap showed Mei Lin's Stats. Negative control: with the name check taken away, the corner is pressed."""
        self.run_screens([LIST, STATS_NOT_SELENA])
        self.assertPressedTexts(None, None)
        self.assertAlmostEqual(0.471, self.task.clicks[0][0], delta=0.002)
        self.assertAlmostEqual(0.041, self.task.clicks[1][0], delta=0.002)
        self.assertIn("Selena", daily.invest_state(self.task)["held"])
        self.task = InvestTask(self.goals)
        self.to_invest()
        with mock.patch.object(invest, "same_name", lambda read, unit: True):
            self.run_screens([LIST, STATS_NOT_SELENA])
        self.assertIn("Promotions", self.task.under[1])

    def test_a_screen_daily_does_not_know_drops_the_check_so_a_panel_is_left_unspent(self):
        """Negative control: the same panel straight after the Stats read gets its Promotions pressed."""
        self.task.config[daily.GOALS_SETTING] = ["Mei Lin"]
        self.run_screens([LIST, STATS, ()] + [PROMOTION_READY] * SETTLED)
        self.assertNotIn(["Promotions"], self.task.under[2:])
        self.assertAlmostEqual(0.041, self.task.clicks[-1][0], delta=0.002)
        self.task = InvestTask(("Mei Lin",))
        self.to_invest()
        self.run_screens([LIST, STATS] + [PROMOTION_READY] * SETTLED)
        self.assertEqual(["Promotions"], [text for text in self.task.under[-1] if text == "Promotions"])
        self.assertAlmostEqual(0.859, self.task.clicks[-1][0], delta=0.002)

    def test_the_combatant_list_drops_the_check_whatever_the_visit_s_state(self):
        """The list itself drops the check, not only the end of a visit: a check left set by mistake reaches no panel. The handlers never
        leave one set on the list today, so the state is made by hand. Negative control: without the list, the same panel promotes."""
        self.task.config[daily.GOALS_SETTING] = ["Mei Lin"]
        visit = self.visiting()
        visit["arrived"] = False
        self.run_screens([LIST] + [PROMOTION_READY] * SETTLED)
        self.assertNotIn(["Promotions"], self.task.under)
        self.task = InvestTask(("Mei Lin",))
        self.to_invest()
        self.visiting()["arrived"] = False
        self.run_screens([PROMOTION_READY] * SETTLED)
        self.assertPressed(daily.PROMOTE)


class TestPromotion(Invest):

    def test_a_ready_panel_promotes_once_after_it_has_read_unchanged_for_three_seconds(self):
        """Negative control: with no settle, the first pass presses."""
        self.visiting()
        self.run_screens([PROMOTION_READY] * daily.PANEL_SETTLE)
        self.assertEqual([], self.task.clicks)
        self.run_screens([PROMOTION_READY])
        self.assertPressed(daily.PROMOTE)
        self.run_screens([PROMOTION_READY] * (daily.SPEND_WAIT - 1))
        self.assertPressed(daily.PROMOTE)
        self.task = InvestTask()
        self.to_invest()
        self.visiting()
        with mock.patch.object(daily, "PANEL_SETTLE", 0):
            self.run_screens([PROMOTION_READY])
        self.assertPressed(daily.PROMOTE)

    def test_the_opening_press_is_made_once_and_a_stats_tab_that_still_reads_presses_nothing(self):
        """Negative control: without the guard the second Stats pass presses the corner again."""
        self.visiting()
        self.run_screens([STATS] * 3 + [PROMOTION_READY])
        self.assertPressed(daily.OPEN_PROMOTION)
        self.task = InvestTask()
        self.to_invest()
        self.visiting()
        def free(task, target, box, signature, opening=True):
            return daily.press_invest(task, target, box)

        with mock.patch.object(daily, "guarded_press", free):
            self.run_screens([STATS] * 2)
        self.assertPressed(daily.OPEN_PROMOTION, daily.OPEN_PROMOTION)

    def test_a_stats_tab_read_again_differently_is_still_the_screen_the_press_was_made_on(self):
        """OCR wavering on the Stats tab frees nothing. Negative control: freed by any change, the corner is pressed twice."""
        jittered = edited(STATS_BELOW_CAP, ("Lv.20/30", "Lv.21/30"))
        self.visiting(phase=daily.TO_LEVEL)
        self.run_screens([STATS_BELOW_CAP, jittered, STATS_BELOW_CAP])
        self.assertPressed(daily.OPEN_LEVEL_UP)
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_LEVEL)
        with mock.patch.object(daily, "STEADY_SCREENS", ()):
            self.run_screens([STATS_BELOW_CAP, jittered])
        self.assertPressed(daily.OPEN_LEVEL_UP, daily.OPEN_LEVEL_UP)

    def test_a_panel_that_does_not_open_in_time_skips_the_unit(self):
        self.visiting()
        self.run_screens([STATS] * (daily.PANEL_WAIT + 2))
        self.assertPressed(daily.OPEN_PROMOTION, daily.DETAILS_LEAVE)
        self.assertIn("Mei Lin: its upgrade panel did not open", daily.invest_state(self.task)["notes"])

    def test_obtain_by_merging_is_short_written_and_left(self):
        """Negative controls: without the go-word rule the stem refusal stops Daily; without both, the merge is pressed."""
        self.visiting()
        self.run_screens([PROMOTION_MERGE])
        self.assertPressed(daily.PANEL_LEAVE)
        self.assertNeverPressed()
        line = daily.invest_state(self.task)["lines"][("Mei Lin", invest.PROMOTION)]
        self.assertEqual((13, 15, 70_000, "Obtain by Merging", "Combatant Promotion Materials - Striker"),
                         (line["have"], line["need"], line["units"], line["caption"], line["stage"]))
        for refused, pressed in ((invest.refused, False), (lambda text: None, True)):
            self.task = InvestTask()
            self.to_invest()
            self.visiting()
            with mock.patch.object(invest, "promotion_go", lambda panel, floor: None), mock.patch.object(invest, "refused", refused):
                self.run_screens([PROMOTION_MERGE] * SETTLED)
            self.assertEqual(pressed, ["Obtain by Merging"] in self.task.under)
            if not pressed:
                self.assertStopped("would have pressed 'Obtain by Merging'")

    def test_replenish_materials_is_short_and_never_pressed(self):
        self.visiting()
        self.run_screens([PROMOTION_REPLENISH])
        self.assertPressed(daily.PANEL_LEAVE)
        self.assertEqual("Replenish Materials", daily.invest_state(self.task)["lines"][("Mei Lin", invest.PROMOTION)]["caption"])

    def test_a_garbled_mission_caption_is_short_written_without_a_stage_and_nothing_stops(self):
        """No refusal word catches it, only the go-word rule. Negative control: without that rule it is pressed."""
        self.visiting(phase=daily.TO_PARTNER)
        self.run_screens([PARTNER_MISSION])
        self.assertPressed(daily.PANEL_LEAVE)
        self.assertEqual(0, self.task.disabled)
        line = daily.invest_state(self.task)["lines"][("Mei Lin", invest.PARTNER_PROMOTION)]
        self.assertEqual(("Clear thePtinissioIteepn]", ""), (line["caption"], line["stage"]))
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_PARTNER)["partner_action"] = invest.PARTNER_PROMOTION
        with mock.patch.object(invest, "promotion_go", lambda panel, floor: None):
            self.run_screens([PARTNER_MISSION] * SETTLED)
        self.assertIn(["Clear thePtinissioIteepn]"], self.task.under)

    def test_a_met_counter_under_the_units_floor_is_not_pressed_and_writes_no_line(self):
        """Negative control: with a floor it clears, it promotes."""
        self.task.config[daily.FLOOR_SETTING] = 2_600_000
        self.visiting()
        self.run_screens([PROMOTION_READY])
        self.assertPressed(daily.PANEL_LEAVE)
        self.assertEqual({}, daily.invest_state(self.task)["lines"])
        self.assertTrue(any("under the 2,600,000 to keep" in note for note in daily.invest_state(self.task)["notes"]))
        self.task = InvestTask(floor=2_500_000)
        self.to_invest()
        self.visiting()
        self.run_screens([PROMOTION_READY] * SETTLED)
        self.assertPressed(daily.PROMOTE)

    def test_a_units_header_that_does_not_read_presses_nothing(self):
        """Without the header the panel is no panel, and nothing is pressed on it."""
        self.visiting()
        self.run_screens([edited(PROMOTION_READY, ("2656K", "2.65M"))] * SETTLED)
        self.assertEqual([], self.task.clicks)

    def test_one_promotion_per_unit_per_run(self):
        """Negative control: before any promotion the same panel is pressed."""
        visit = self.visiting()
        visit["spent"][invest.PROMOTION] = 1
        self.run_screens([PROMOTION_READY])
        self.assertPressed(daily.PANEL_LEAVE)
        self.task = InvestTask()
        self.to_invest()
        self.visiting()
        self.run_screens([PROMOTION_READY] * SETTLED)
        self.assertPressed(daily.PROMOTE)

    def test_two_spends_in_a_row_that_change_nothing_stop_daily(self):
        """Negative control: one spend that changes nothing only leaves the panel."""
        self.visiting()
        self.run_screens([PROMOTION_READY] * (SETTLED + daily.SPEND_WAIT + 1))
        self.assertPressed(daily.PROMOTE, daily.PANEL_LEAVE)
        self.assertEqual(0, self.task.disabled)
        self.task = InvestTask()
        self.to_invest()
        self.visiting()
        daily.invest_state(self.task)["misses"] = 1
        self.run_screens([PROMOTION_READY] * (SETTLED + daily.SPEND_WAIT + 1))
        self.assertStopped("2 upgrade presses in a row changed nothing")

    def test_a_dialog_over_the_panel_gets_nothing_pressed(self):
        """Neither 确认 nor 取消 nor the back arrow. Negative control: read as the panel under it, it would be left."""
        self.visiting(phase=daily.TO_PARTNER)
        self.run_screens([REPLENISH_DIALOG] * (daily.UNKNOWN_SECONDS + 1))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("does not know this screen")
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_PARTNER)
        panel = invest.promotion_panel(Task().show(ROSARIA_PROMOTION))
        with mock.patch.object(invest, "promotion_panel", lambda task: panel):
            self.run_screens([REPLENISH_DIALOG])
        self.assertEqual(1, len(self.task.clicks))

    def test_the_merge_dialog_gets_nothing_pressed(self):
        self.visiting()
        self.run_screens([MERGE_DIALOG] * 3)
        self.assertEqual([], self.task.clicks)


class TestCapturedPromotion(Invest):
    """Mei Lin's promotion 20 to 30 and her levels, in the order the live client showed them."""

    def test_promote_level_and_leave_on_the_mission_panel(self):
        self.run_screens([LOBBY, LIST, STATS] + [PROMOTION_READY] * SETTLED + [PROMOTED, LEVEL_PANEL] + [LEVEL_REGISTERED] * SETTLED
                         + [LEVELLED, RETURN_ITEM, MISSION, STATS_30])
        self.assertPressed(daily.INVEST_ENTRY, daily.UNIT_CARD, daily.OPEN_PROMOTION, daily.PROMOTE, daily.RESULT_CLOSE, daily.AUTO_REGISTER,
                           daily.LEVEL_UP, daily.RESULT_CLOSE, daily.RESULT_CLOSE, daily.PANEL_LEAVE, daily.PARTNERS_TAB)
        self.assertNeverPressed()
        self.assertEqual(["点击屏幕关闭窗口"], self.task.under[8])
        inv = daily.invest_state(self.task)
        self.assertEqual([("Mei Lin", invest.PROMOTION), ("Mei Lin", invest.LEVEL)], inv["spends"])
        line = inv["lines"][("Mei Lin", invest.PROMOTION)]
        self.assertEqual((0, 32, 150_000, "Clear the Promotion Mission [Veteran Captain]", ""),
                         (line["have"], line["need"], line["units"], line["caption"], line["stage"]))
        self.assertTrue(any("investing in Mei Lin: promotion, 15/15, 70,000 of 2,656,000 Units" in line for line in self.task.logged))
        self.assertTrue(any("investing in Mei Lin: level, Lv.20+10, 13,020 of 2,586,000 Units" in line for line in self.task.logged))

    def test_the_return_item_card_is_closed_by_its_caption_never_its_enter(self):
        """Negative control: a tap on `进入` would show among the captions under the tap."""
        self.visiting(phase=daily.TO_LEVEL)
        self.run_screens([RETURN_ITEM])
        self.assertEqual([["点击屏幕关闭窗口"]], self.task.under)
        self.task.under.clear()
        self.task.show(RETURN_ITEM).click(0.500, 0.978)
        self.assertIn("进入", self.task.under[0])


class TestLevelUp(Invest):

    def test_auto_register_comes_first_and_only_the_corner_level_up_is_pressed(self):
        """Marianne's panels. Negative control: without the Auto Register rule, Level Up is pressed on the empty panel."""
        self.visiting(phase=daily.TO_PARTNER)
        self.run_screens([PARTNERS] + [PARTNER_READY] * SETTLED + [PARTNER_PROMOTED, PARTNER_LEVEL] + [PARTNER_REGISTERED] * SETTLED
                         + [PARTNER_LEVELLED, PARTNER_RETURN, PARTNER_MISSION])
        self.assertPressed(daily.PARTNER_UPGRADE, daily.PROMOTE, daily.RESULT_CLOSE, daily.AUTO_REGISTER, daily.LEVEL_UP, daily.RESULT_CLOSE,
                           daily.RESULT_CLOSE, daily.PANEL_LEAVE)
        for x, y in self.task.clicks:
            self.assertFalse(abs(x - 0.064) < 0.01 and abs(y - 0.351) < 0.01, "pressed the Level Up tab")
            self.assertFalse(abs(x - 0.851) < 0.01 and abs(y - 0.12) < 0.01, "pressed the Level Up title")
        self.assertNeverPressed()
        self.assertEqual([("Mei Lin", invest.PARTNER_PROMOTION), ("Mei Lin", invest.PARTNER_LEVEL)], daily.invest_state(self.task)["spends"])
        self.task = InvestTask()
        self.to_invest()
        visit = self.visiting(phase=daily.TO_PARTNER)
        visit["registered"] = -100
        with mock.patch.object(invest, "level_go", lambda panel, floor: None):
            self.run_screens([PARTNER_LEVEL] * SETTLED)
        self.assertPressed(daily.LEVEL_UP)

    def test_auto_register_giving_no_levels_presses_no_level_up(self):
        """Negative control: without the gain check, Level Up is pressed on Lv.20+0."""
        self.visiting(phase=daily.TO_LEVEL)
        self.run_screens([LEVEL_PANEL] * (daily.REGISTER_WAIT + 2))
        self.assertPressed(daily.AUTO_REGISTER, daily.PANEL_LEAVE)
        self.assertTrue(any("Auto Register gave no levels" in note for note in daily.invest_state(self.task)["notes"]))
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_LEVEL)
        with mock.patch.object(invest, "level_go", lambda panel, floor: None):
            self.run_screens([LEVEL_PANEL] * (daily.REGISTER_WAIT + 2))
        self.assertPressed(daily.AUTO_REGISTER, daily.LEVEL_UP)

    def test_under_a_million_units_the_header_reads_whole_and_level_up_is_pressed(self):
        """`888,680` held, 840 to pay. Negative control: read as `NNNNK` only, the panel is no panel and nothing is pressed."""
        self.visiting(phase=daily.TO_LEVEL)
        self.run_screens([LEVEL_PLAIN_UNITS] * SETTLED)
        self.assertPressed(daily.LEVEL_UP)
        self.assertTrue(any("investing in Mei Lin: level, Lv.1+9, 840 of 888,680 Units" in line for line in self.task.logged))
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_LEVEL)
        with mock.patch.object(invest, "UNITS", invest.re.compile(r"(\d+)[kK]")):
            self.run_screens([LEVEL_PLAIN_UNITS] * SETTLED)
        self.assertEqual([], self.task.clicks)

    def test_a_level_up_panel_whose_corner_reads_otherwise_gets_no_auto_register(self):
        """A tutorial line's `Space` over a Partner's panel: only the back arrow. Control: the same panel with `Level Up` there gets Auto Register."""
        self.visiting(phase=daily.TO_PARTNER)["partner_action"] = invest.PARTNER_LEVEL
        self.run_screens([TUTORIAL_OVER_LEVEL])
        self.assertPressed(daily.PANEL_LEAVE)
        self.assertNotIn(["Auto Register"], self.task.under)
        self.assertIn("Mei Lin partner level: the button reads 'Space'", daily.invest_state(self.task)["notes"])
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_PARTNER)["partner_action"] = invest.PARTNER_LEVEL
        self.run_screens([edited(TUTORIAL_OVER_LEVEL, ("Space", "Level Up"))])
        self.assertPressed(daily.AUTO_REGISTER)

    def test_level_go_refuses_any_corner_caption_but_level_up(self):
        """Daily checks the caption before Auto Register as well; the decision holds without it. Negative control: `Level Up` there may go."""
        frame = Task().show(replaced_at(LEVEL_REGISTERED, (0.859, 0.920), "Replenish Materials"))
        panel = invest.level_panel(frame)
        self.assertEqual("the button reads 'Replenish Materials'", invest.level_go(panel, daily.UNITS_FLOOR))
        self.assertIsNone(invest.level_go(invest.level_panel(Task().show(LEVEL_REGISTERED)), daily.UNITS_FLOOR))

    def test_level_up_is_not_pressed_under_the_units_floor_or_with_its_cost_unread(self):
        """2,586,000 held, 13,020 to pay, 2,580,000 to keep; then the cost not read. Negative control: with 2,500,000 to keep, it levels."""
        self.task.config[daily.FLOOR_SETTING] = 2_580_000
        self.visiting(phase=daily.TO_LEVEL)
        self.run_screens([LEVEL_REGISTERED] * SETTLED)
        self.assertOnlyPressed(daily.PANEL_LEAVE)
        self.assertTrue(any("under the 2,580,000 to keep" in note for note in daily.invest_state(self.task)["notes"]))
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_LEVEL)
        self.run_screens([without(LEVEL_REGISTERED, "13,020")] * SETTLED)
        self.assertOnlyPressed(daily.PANEL_LEAVE)
        self.assertTrue(any("the Units did not read" in note for note in daily.invest_state(self.task)["notes"]))
        self.task = InvestTask(floor=2_500_000)
        self.to_invest()
        self.visiting(phase=daily.TO_LEVEL)
        self.run_screens([LEVEL_REGISTERED] * SETTLED)
        self.assertPressed(daily.LEVEL_UP)

    def test_level_up_waits_for_a_panel_that_has_read_unchanged_for_three_seconds(self):
        """Negative control: with no settle, the first pass levels."""
        self.visiting(phase=daily.TO_LEVEL)
        self.run_screens([LEVEL_REGISTERED] * daily.PANEL_SETTLE)
        self.assertEqual([], self.task.clicks)
        self.run_screens([LEVEL_REGISTERED])
        self.assertPressed(daily.LEVEL_UP)
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_LEVEL)
        with mock.patch.object(daily, "PANEL_SETTLE", 0):
            self.run_screens([LEVEL_REGISTERED])
        self.assertPressed(daily.LEVEL_UP)

    def test_a_level_up_panel_is_left_unspent_without_the_name_check(self):
        """Negative control: the same panel with the name read gets Level Up pressed."""
        self.visiting(phase=daily.TO_LEVEL)["checked"] = False
        self.run_screens([LEVEL_REGISTERED] * SETTLED)
        self.assertFalse(any("Level Up" in under or "Auto Register" in under for under in self.task.under))
        self.assertOnlyPressed(daily.PANEL_LEAVE)
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_LEVEL)
        self.run_screens([LEVEL_REGISTERED] * SETTLED)
        self.assertPressed(daily.LEVEL_UP)

    def test_three_level_up_presses_a_panel_at_most(self):
        visit = self.visiting(phase=daily.TO_LEVEL)
        visit["spent"][invest.LEVEL] = daily.LEVEL_CYCLES
        self.run_screens([LEVEL_REGISTERED])
        self.assertPressed(daily.PANEL_LEAVE)

    def test_a_later_unit_leaves_its_level_up_while_an_earlier_one_holds_the_materials(self):
        """The hold reaches the Level Up panel. Negative control: with nobody holding, it levels."""
        self.task.config[daily.GOALS_SETTING] = ["Mei Lin", "Selena"]
        self.visiting("Selena", phase=daily.TO_LEVEL)
        daily.invest_state(self.task)["held"].add("Mei Lin")
        self.run_screens([LEVEL_REGISTERED])
        self.assertPressed(daily.PANEL_LEAVE)
        daily.invest_state(self.task)["held"].clear()
        self.task.clicks.clear()
        self.visiting("Selena", phase=daily.TO_LEVEL)
        self.run_screens([LEVEL_REGISTERED] * SETTLED)
        self.assertPressed(daily.LEVEL_UP)


def OLD_HOLD(panel, reason):
    """The hold the old rule made: any Promotion that was not pressed."""
    return reason is not None


def NO_HOLD(panel, reason):
    """No hold from a Promotion at all."""
    return False


class TestLevelHold(Invest):
    """A later goal unit's Level Up waits only while the unit before it can use what Level Up spends: unread, below its cap, or its Promotion ready but for the Units."""

    goals = ("Mei Lin", "Selena")

    def earlier(self, screen):
        """Read Mei Lin's screen and end her visit, as leaving Details does, then stand on Selena's Level Up."""
        self.visiting("Mei Lin")
        self.run_screens([screen])
        daily.end_visit(self.task)
        self.task.clicks.clear()
        self.visiting("Selena", phase=daily.TO_LEVEL)

    def selena_levels(self):
        self.run_screens([LEVEL_PANEL] + [LEVEL_REGISTERED] * SETTLED)

    def again(self):
        self.task = InvestTask(self.goals)
        self.to_invest()

    def test_a_promotion_waiting_on_its_mission_holds_nobody(self):
        """Mei Lin at 30/30 on the mission panel. Negative control: with the old rule, Selena's Level Up is left."""
        self.earlier(MISSION)
        self.selena_levels()
        self.assertPressed(daily.AUTO_REGISTER, daily.LEVEL_UP)
        self.again()
        with mock.patch.object(invest, "held_by_units", OLD_HOLD):
            self.earlier(MISSION)
            self.run_screens([LEVEL_PANEL])
        self.assertPressed(daily.PANEL_LEAVE)

    def test_a_ready_promotion_under_the_units_floor_holds_the_later_level_up(self):
        """350K held, 70,000 to pay, 300,000 to keep. Negative control: without the hold, Selena levels. The old rule held here too."""
        self.earlier(edited(PROMOTION_READY, ("2656K", "350K")))
        self.run_screens([LEVEL_PANEL])
        self.assertPressed(daily.PANEL_LEAVE)
        self.assertIn("Selena: level left for a goal unit listed before it", daily.invest_state(self.task)["notes"])
        self.again()
        with mock.patch.object(invest, "held_by_units", NO_HOLD):
            self.earlier(edited(PROMOTION_READY, ("2656K", "350K")))
            self.selena_levels()
        self.assertPressed(daily.AUTO_REGISTER, daily.LEVEL_UP)

    def test_a_promotion_short_of_manuals_at_the_cap_holds_nobody(self):
        """`Promotions` over 13/15 at 20/20. Negative control: with the old rule, Selena's Level Up is left."""
        short = edited(PROMOTION_READY, ("15/15", "13/15"))
        self.earlier(short)
        self.selena_levels()
        self.assertPressed(daily.AUTO_REGISTER, daily.LEVEL_UP)
        self.again()
        with mock.patch.object(invest, "held_by_units", OLD_HOLD):
            self.earlier(short)
            self.run_screens([LEVEL_PANEL])
        self.assertPressed(daily.PANEL_LEAVE)

    def test_an_earlier_unit_below_its_cap_holds_the_later_level_up(self):
        """Mei Lin's Stats at 20/30. Control: the same visit at 20/20 lets Selena level."""
        self.earlier(STATS_BELOW_CAP)
        self.run_screens([LEVEL_PANEL])
        self.assertPressed(daily.PANEL_LEAVE)
        self.again()
        self.earlier(STATS)
        self.selena_levels()
        self.assertPressed(daily.AUTO_REGISTER, daily.LEVEL_UP)


class TestPartner(Invest):

    def test_a_强化_run_into_change_is_not_pressed_and_nothing_stops(self):
        """Negative control: matched by containing 强化 anywhere along the button row, the merged box is pressed."""
        self.visiting(phase=daily.TO_PARTNER)
        self.run_screens([PARTNERS_MERGED])
        self.assertPressed(daily.POTENTIAL_TAB)
        self.assertEqual(0, self.task.disabled)
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_PARTNER)
        def loose(task, word, region):
            return next((box for box in invest.boxes_in(task, region) if word in invest.folded(box.name)), None)

        with mock.patch.object(invest, "equal_in", loose), mock.patch.object(invest, "UPGRADE_REGION", (0.77, 0.90, 0.95, 0.95)):
            self.run_screens([PARTNERS_MERGED])
        self.assertIn(["强化 Change"], self.task.under)

    def test_a_partner_levelled_to_its_cap_is_not_promoted_in_the_same_visit(self):
        """Its `强化` opened the Level Up panel, so the Promotions panel levelling ends on is left. Negative control: opened for it, it promotes."""
        self.visiting(phase=daily.TO_PARTNER)["partner_action"] = invest.PARTNER_LEVEL
        self.run_screens([PARTNER_READY])
        self.assertPressed(daily.PANEL_LEAVE)
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_PARTNER)["partner_action"] = invest.PARTNER_PROMOTION
        self.run_screens([PARTNER_READY] * SETTLED)
        self.assertPressed(daily.PROMOTE)

    def test_a_combatant_with_no_partner_goes_on_to_potential(self):
        """Rei's and Owen's tabs: Potential next, `Assign Partner` never pressed, named in the finish line. Negative control: unread, the tab is a
        screen Daily does not know and nothing is pressed."""
        for screen in (NO_PARTNER, OWEN_NO_PARTNER):
            with self.subTest(screen=screen[0][0]):
                self.task = InvestTask()
                self.to_invest()
                self.visiting(phase=daily.TO_PARTNER)
                self.run_screens([screen, MAP])
                self.assertPressed(daily.POTENTIAL_TAB, daily.NODE_01_ENTRY)
                self.assertNeverPressed()
                self.assertIn("Mei Lin: no Partner assigned", daily.invest_state(self.task)["notes"])
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_PARTNER)
        with mock.patch.object(invest, "no_partner_tab", lambda task: False):
            self.run_screens([NO_PARTNER])
        self.assertEqual([], self.task.clicks)

    def test_a_no_partner_tab_without_the_name_check_goes_back_to_stats(self):
        self.visiting(phase=daily.TO_PARTNER)["checked"] = False
        self.run_screens([NO_PARTNER])
        self.assertPressed(daily.STATS_TAB)

    def test_a_held_unit_s_partner_level_up_is_not_opened_from_the_partners_tab(self):
        """Marianne below her cap while Mei Lin holds the materials: Potential next, no `强化`. Negative control: with nobody holding, `强化` is pressed."""
        below_cap = edited(PARTNERS, ("Lv.10/10", "Lv.5/10"))
        self.task.config[daily.GOALS_SETTING] = ["Mei Lin", "Selena"]
        self.visiting("Selena", phase=daily.TO_PARTNER)
        daily.invest_state(self.task)["held"].add("Mei Lin")
        self.run_screens([below_cap])
        self.assertPressed(daily.POTENTIAL_TAB)
        self.assertIn("Selena: its Partner's Level Up left for a goal unit listed before it", daily.invest_state(self.task)["notes"])
        daily.invest_state(self.task)["held"].clear()
        self.task.clicks.clear()
        self.visiting("Selena", phase=daily.TO_PARTNER)
        self.run_screens([below_cap])
        self.assertPressed(daily.PARTNER_UPGRADE)

    def test_a_short_partner_promotion_is_written_with_its_partner_s_stage(self):
        self.visiting(phase=daily.TO_PARTNER)
        self.run_screens([PARTNERS, PARTNER_SHORT, PARTNERS])
        self.assertPressed(daily.PARTNER_UPGRADE, daily.PANEL_LEAVE, daily.POTENTIAL_TAB)
        line = daily.invest_state(self.task)["lines"][("Mei Lin", invest.PARTNER_PROMOTION)]
        self.assertEqual((0, 6, "Obtain through dismanting", "Partner Promotion Materials - Striker"), (line["have"], line["need"], line["caption"], line["stage"]))


class TestPotential(Invest):

    def test_node_02_behind_promotion_required_is_short_though_its_counter_is_met(self):
        """Negative controls: without the go-word rule the stem refusal stops Daily; without both it is pressed."""
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["node"] = "02"
        self.run_screens([NODE_02_GATED])
        self.assertPressed(daily.NODE_LEAVE)
        self.assertEqual("", daily.invest_state(self.task)["lines"][("Mei Lin", invest.NODE_02)]["stage"])
        for refused, pressed in ((invest.refused, False), (lambda text: None, True)):
            self.task = InvestTask()
            self.to_invest()
            self.visiting(phase=daily.TO_POTENTIAL)["node"] = "02"
            with mock.patch.object(invest, "node_go", lambda node, floor: None), mock.patch.object(invest, "refused", refused):
                self.run_screens([NODE_02_GATED] * SETTLED)
            self.assertEqual(pressed, ["Promotion required"] in self.task.under)

    def test_a_caption_containing_the_go_word_is_not_pressed(self):
        """`Activated`, a caption made up for this test. Negative control: matched as a substring, it is pressed."""
        activated = edited(NODE_01_READY, ("Activate", "Activated"))
        self.visiting(phase=daily.TO_POTENTIAL)["node"] = "01"
        self.run_screens([activated])
        self.assertPressed(daily.NODE_LEAVE)
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_POTENTIAL)["node"] = "01"
        def loose(node, floor):
            return None if "activate" in node.caption else "short"

        with mock.patch.object(invest, "node_go", loose):
            self.run_screens([activated] * SETTLED)
        self.assertIn(["Activated"], self.task.under)

    def test_node_01_once_and_node_02_on_the_first_goal_unit_until_its_promotion_gate(self):
        self.visiting(phase=daily.TO_POTENTIAL)
        self.run_screens([MAP] + [NODE_01_READY] * SETTLED + [NODE_CARD] + [NODE_01_DONE] * SETTLED + [MAP] + [NODE_02] * SETTLED + [NODE_CARD]
                         + [NODE_02_LV2] * SETTLED + [NODE_CARD, NODE_02_GATED, MAP])
        self.assertPressed(daily.NODE_01_ENTRY, daily.ACTIVATE, daily.RESULT_CLOSE, daily.NODE_LEAVE, daily.NODE_02_ENTRY, daily.ACTIVATE,
                           daily.RESULT_CLOSE, daily.ACTIVATE, daily.RESULT_CLOSE, daily.NODE_LEAVE, daily.DETAILS_LEAVE)
        inv = daily.invest_state(self.task)
        self.assertEqual([("Mei Lin", invest.NODE_01), ("Mei Lin", invest.NODE_02), ("Mei Lin", invest.NODE_02)], inv["spends"])
        self.assertEqual([("Mei Lin", invest.NODE_02)], list(inv["lines"]))

    def test_an_active_node_01_is_left_and_every_goal_unit_is_visited(self):
        """Mei Lin's and Selena's node 01 already active: each is left by the back arrow, Mei Lin's node 02 is opened, and the
        goal file is written. Negative control: unread, the active panel stops Daily with only node 01's tap made."""
        self.task.config[daily.GOALS_SETTING] = ["Mei Lin", "Selena"]
        self.visiting(phase=daily.TO_POTENTIAL)
        self.run_screens([MAP] + [NODE_01_DONE] * SETTLED + [MAP, NODE_02_GATED, MAP])
        self.assertPressed(daily.NODE_01_ENTRY, daily.NODE_LEAVE, daily.NODE_02_ENTRY, daily.NODE_LEAVE, daily.DETAILS_LEAVE)
        self.task.clicks.clear()
        self.visiting("Selena", phase=daily.TO_POTENTIAL)
        self.run_screens([MAP] + [SELENA_NODE_01_DONE] * SETTLED + [MAP, LIST, LOBBY])
        self.assertPressed(daily.NODE_01_ENTRY, daily.NODE_LEAVE, daily.DETAILS_LEAVE, daily.LIST_LEAVE)
        self.assertNeverPressed()
        self.assertEqual([("Mei Lin", invest.NODE_02)], [(line["unit"], line["action"]) for line in self.lines()])
        self.assertStopped("Daily finished")
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_POTENTIAL)
        with mock.patch.object(invest, "done_node", lambda task: None):
            self.run_screens([MAP] + [NODE_01_DONE] * (daily.UNKNOWN_SECONDS + 1))
        self.assertPressed(daily.NODE_01_ENTRY)
        self.assertStopped("does not know this screen")

    def test_an_active_node_panel_is_left_only_once_it_has_read_unchanged(self):
        """A panel whose counter and button have not drawn yet must not pass for a done node. Negative control: with no wait, the first pass leaves."""
        self.visiting(phase=daily.TO_POTENTIAL)["node"] = "01"
        self.run_screens([NODE_01_DONE] * daily.PANEL_SETTLE)
        self.assertEqual([], self.task.clicks)
        self.run_screens([NODE_01_DONE])
        self.assertPressed(daily.NODE_LEAVE)
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_POTENTIAL)["node"] = "01"
        with mock.patch.object(daily, "PANEL_SETTLE", 0):
            self.run_screens([NODE_01_DONE])
        self.assertPressed(daily.NODE_LEAVE)

    def test_node_02_at_its_last_level_is_not_opened(self):
        """The map's counter reads 10/10. Negative control: read as not full, node 02 is opened."""
        full = edited(MAP, ("5/10", "10/10"))
        self.visiting(phase=daily.TO_POTENTIAL)["nodes_done"].add("01")
        self.run_screens([full])
        self.assertPressed(daily.DETAILS_LEAVE)
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_POTENTIAL)["nodes_done"].add("01")
        with mock.patch.object(invest, "node_02_full", lambda task: False):
            self.run_screens([full])
        self.assertPressed(daily.NODE_02_ENTRY)

    def test_activate_waits_for_a_panel_that_has_read_unchanged_for_three_seconds(self):
        """Negative control: with no settle, the first pass activates."""
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["node"], visit["nodes_done"] = "02", {"01"}
        self.run_screens([NODE_02] * daily.PANEL_SETTLE)
        self.assertEqual([], self.task.clicks)
        self.run_screens([NODE_02])
        self.assertPressed(daily.ACTIVATE)
        self.task = InvestTask()
        self.to_invest()
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["node"], visit["nodes_done"] = "02", {"01"}
        with mock.patch.object(daily, "PANEL_SETTLE", 0):
            self.run_screens([NODE_02])
        self.assertPressed(daily.ACTIVATE)

    def test_activate_is_not_pressed_under_the_units_floor(self):
        """2,320,000 held, 3,000 to pay. Negative control: with 2,317,000 to keep, it activates."""
        self.task.config[daily.FLOOR_SETTING] = 2_318_000
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["node"], visit["nodes_done"] = "02", {"01"}
        self.run_screens([NODE_02] * SETTLED)
        self.assertOnlyPressed(daily.NODE_LEAVE)
        self.assertTrue(any("under the 2,318,000 to keep" in note for note in daily.invest_state(self.task)["notes"]))
        self.task = InvestTask(floor=2_317_000)
        self.to_invest()
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["node"], visit["nodes_done"] = "02", {"01"}
        self.run_screens([NODE_02] * SETTLED)
        self.assertPressed(daily.ACTIVATE)

    def test_activate_is_not_pressed_on_an_unmet_counter(self):
        """3/4 stones. Negative control: 14/4 activates."""
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["node"], visit["nodes_done"] = "02", {"01"}
        self.run_screens([edited(NODE_02, ("14/4", "3/4"))] * SETTLED)
        self.assertOnlyPressed(daily.NODE_LEAVE)
        self.task = InvestTask()
        self.to_invest()
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["node"], visit["nodes_done"] = "02", {"01"}
        self.run_screens([NODE_02] * SETTLED)
        self.assertPressed(daily.ACTIVATE)

    def test_a_node_panel_is_left_unspent_without_the_name_check(self):
        """Negative control: the same panel with the name read gets Activate pressed."""
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit.update(node="02", nodes_done={"01"}, checked=False)
        self.run_screens([NODE_02] * SETTLED)
        self.assertNotIn(["Activate"], self.task.under)
        self.assertOnlyPressed(daily.NODE_LEAVE)
        self.task = InvestTask()
        self.to_invest()
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit.update(node="02", nodes_done={"01"})
        self.run_screens([NODE_02] * SETTLED)
        self.assertPressed(daily.ACTIVATE)

    def test_a_press_is_refused_when_a_never_press_caption_lies_under_its_point(self):
        """Node 01's tap is a fixed point, so only the boxes under it can refuse it. Negative control: the plain map gets node 01 tapped."""
        self.visiting(phase=daily.TO_POTENTIAL)
        self.run_screens([MAP + (("Dismantle", 0.309, 0.814),)])
        self.assertEqual([], self.task.clicks)
        self.assertStopped("would have pressed 'Dismantle'")
        self.task = InvestTask()
        self.to_invest()
        self.visiting(phase=daily.TO_POTENTIAL)
        self.run_screens([MAP])
        self.assertPressed(daily.NODE_01_ENTRY)

    def test_a_later_goal_unit_gets_node_01_only(self):
        """Negative control: the first goal unit's map opens node 02 next."""
        self.task.config[daily.GOALS_SETTING] = ["Mei Lin", "Selena"]
        self.visiting("Selena", phase=daily.TO_POTENTIAL)["nodes_done"].add("01")
        self.run_screens([MAP])
        self.assertPressed(daily.DETAILS_LEAVE)
        self.task.clicks.clear()
        self.visiting("Mei Lin", phase=daily.TO_POTENTIAL)["nodes_done"].add("01")
        self.run_screens([MAP])
        self.assertPressed(daily.NODE_02_ENTRY)

    def test_ten_node_levels_per_unit_at_most(self):
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["node"], visit["nodes_done"] = "02", {"01"}
        visit["spent"][invest.NODE_02] = daily.ACTIVATE_CAP
        self.run_screens([NODE_02])
        self.assertPressed(daily.NODE_LEAVE)

    def test_a_node_panel_naming_another_node_is_left_unpressed(self):
        self.visiting(phase=daily.TO_POTENTIAL)["node"] = "01"
        self.run_screens([NODE_02])
        self.assertPressed(daily.NODE_LEAVE)

    def test_the_blended_frame_gets_nothing_pressed(self):
        """Negative control: taken for the Potential map, it would get node 01 tapped on the Lobby's menu."""
        self.visiting(phase=daily.TO_POTENTIAL)
        self.run_screens([BLENDED])
        self.assertEqual([], self.task.clicks)
        self.visiting(phase=daily.TO_POTENTIAL)
        match = mock.Mock()
        match.group.side_effect = {0: "5/10", 1: "5", 2: "10"}.get
        with mock.patch.object(invest, "potential_map", lambda task: True), mock.patch.object(invest, "only_match", lambda *args: match):
            self.run_screens([BLENDED])
        self.assertPressed(daily.NODE_01_ENTRY)


class TestClock(Invest):

    def test_the_park_s_clock_does_not_stop_a_run_inside_the_invest_step(self):
        """Negative control: the same time with the park still pending stops."""
        self.state()["park"]["started"] = daily.time.monotonic() - daily.PARK_SECONDS + 5
        self.visiting()
        run_pass(self.task.show(LIST))
        self.tick(daily.INVEST_SECONDS - 1)
        run_pass(self.task.show(STATS))
        self.assertEqual(0, self.task.disabled)
        self.tick()
        run_pass(self.task.show(STATS))
        self.assertStopped("the invest step ran for 10 minutes")
        self.task = InvestTask()
        self.to_invest()
        self.state()["steps"][daily.PARK] = daily.PENDING
        self.state()["park"]["started"] = daily.time.monotonic() - daily.PARK_SECONDS
        run_pass(self.task.show(STATS))
        self.assertStopped("the Dream Park visit ran for 10 minutes")


class TestWholeStep(Invest):

    def test_every_short_action_is_written_and_named_and_the_run_finishes(self):
        """The goal file gets every short action, the stage-less ones are named in the finish line, nothing is spent."""
        self.run_screens([LOBBY, LIST, STATS, PROMOTION_MERGE, STATS, PARTNERS, PARTNER_SHORT, PARTNERS, MAP, NODE_01_GATED, MAP, NODE_02_GATED,
                          MAP, LIST, LOBBY])
        self.assertPressed(daily.INVEST_ENTRY, daily.UNIT_CARD, daily.OPEN_PROMOTION, daily.PANEL_LEAVE, daily.PARTNERS_TAB, daily.PARTNER_UPGRADE,
                           daily.PANEL_LEAVE, daily.POTENTIAL_TAB, daily.NODE_01_ENTRY, daily.NODE_LEAVE, daily.NODE_02_ENTRY, daily.NODE_LEAVE,
                           daily.DETAILS_LEAVE, daily.LIST_LEAVE)
        self.assertNeverPressed()
        lines = self.lines()
        self.assertEqual([invest.PROMOTION, invest.PARTNER_PROMOTION, invest.NODE_01, invest.NODE_02], [line["action"] for line in lines])
        self.assertEqual(["Combatant Promotion Materials - Striker", "Partner Promotion Materials - Striker", "", ""], [line["stage"] for line in lines])
        self.assertTrue(all(line["unit"] == "Mei Lin" and line["read_at"] for line in lines))
        self.assertStopped("Invest: Mei Lin: nothing spent, short: promotion 13/15 (Obtain by Merging)")
        self.assertIn("no farming stage for Mei Lin potential node 01 (Promotion required), Mei Lin potential node 02 (Promotion required)",
                      self.task.notifications[0])

    def test_a_met_action_writes_no_line(self):
        """After its spends node 02 writes only its gate; a promoted unit's ready panel writes nothing."""
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["nodes_done"].add("01")
        self.run_screens([MAP] + [NODE_02] * SETTLED + [NODE_CARD, NODE_02_GATED, MAP, LIST, LOBBY])
        self.assertEqual([invest.NODE_02], [line["action"] for line in self.lines()])
        self.assertEqual(6, self.lines()[0]["have"])

    def test_no_short_action_writes_an_empty_goal_file(self):
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["nodes_done"].update({"01", "02"})
        self.run_screens([MAP, LIST, LOBBY])
        self.assertEqual([], self.lines())
        self.assertStopped("Invest: Mei Lin: nothing spent.")

    def test_a_goal_file_that_cannot_be_written_is_named_and_the_run_still_finishes(self):
        visit = self.visiting(phase=daily.TO_POTENTIAL)
        visit["nodes_done"].update({"01", "02"})
        with mock.patch.object(invest, "write_goals", side_effect=OSError("read-only")):
            self.run_screens([MAP, LIST, LOBBY])
        self.assertStopped("the goal file was not written: read-only")


class TestNoSpendGuardChange(unittest.TestCase):

    def test_the_invest_words_stay_out_of_daily_s_shared_refusals(self):
        """The stems are scoped to invest presses, so Daily's other screens and the spend guard are untouched."""
        for text in ("Obtain by Merging", "Replenish Materials", "Change"):
            self.assertIsNone(daily.refused(text))


if __name__ == "__main__":
    unittest.main()
