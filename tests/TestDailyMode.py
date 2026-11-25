"""Check that Daily closes the Lobby's popups, claims attendance, all mail, Activity rewards, achievements, the Carnival's attendance and The Path of a Captain's tiers, opens Dream Park and stops on the Lobby, pressing nothing else.

The screens are the boxes OCR read off the Global client's Lobby, its entry banner and Notice board, the open menu, the
Mail screen before and after Claim All, the Activity window's tabs, the Achievement screen, the Nightmare Carnival,
The Path of a Captain and Items Obtained, as the bot sees them once the catalog has mapped them, with the player's name
left out. What Daily must never do: press a delete, the Shop, a purchase, Crystals, a price, Rescue or the game's quit
button; press a claim that reads `Move`, the Carnival's Make-Up or `Go`; press anything on a screen it does not know; run
beside another mode. The park visit itself is checked in `TestDreamPark`.
"""

import ast
import importlib
import re
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

import utils  # noqa: E402
import utils_chaos  # noqa: E402,F401
import utils_sortie  # noqa: E402,F401
import utils_story  # noqa: E402,F401
from ok import TriggerTask  # noqa: E402
from ok.device.interaction_methods.post_message import PostMessageInteraction  # noqa: E402

from src.en import daily, handlers, skip_tutorial, spend_guard, story, stuck_stop  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402

START = 1_000.0
INSTALLS = 3

# 219, the Lobby with its menu closed.
LOBBY = (
    ("N", 0.136, 0.032), ("m", 0.839, 0.031), ("`", 0.919, 0.023), ("等级", 0.054, 0.049), ("06", 0.055, 0.091), ("240/240+", 0.698, 0.049),
    ("★", 0.777, 0.054), ("E", 0.834, 0.049), ("N", 0.972, 0.03), ("53%", 0.106, 0.084), ("Act 1-Chapter 1, Episode 7", 0.824, 0.194),
    ("故事", 0.884, 0.156), ("Clear Battle Mission Chapt", 0.154, 0.233), ("0/1", 0.064, 0.262), ("Sortie", 0.884, 0.267), ("CAC>", 0.898, 0.292),
    ("O11d Oh", 0.05, 0.333), ("Reach Captain Level 10", 0.104, 0.388), ("θ Simulation", 0.867, 0.354), ("日 Chaos", 0.883, 0.44),
    ("方舟城市", 0.875, 0.528), ("Combatants", 0.867, 0.617), ("EVENT", 0.822, 0.704), ("营救", 0.887, 0.705), ("32d0h", 0.935, 0.832),
    ("CORONOMICON", 0.142, 0.887), ("GIFT", 0.166, 0.921), ("Uponthe SnW", 0.889, 0.925), ("APromrse", 0.894, 0.887),
)
# 265, the Lobby with its menu open.
MENU = (
    ("N", 0.137, 0.032), ("06", 0.057, 0.091), ("53%", 0.105, 0.084), ("Act 1 - Chapter 1, Episode 7", 0.521, 0.130), ("故事", 0.581, 0.091),
    ("⭐", 0.736, 0.091), ("Event", 0.783, 0.087), ("X", 0.961, 0.049), ("Arkhianon Supply", 0.825, 0.160), ("日", 0.904, 0.159),
    ("Mission Chapter 1. B3", 0.118, 0.233), ("θ Sortie", 0.581, 0.200), ("0/1", 0.064, 0.263), ("Activity", 0.789, 0.231),
    ("Simulation", 0.564, 0.288), ("10d23h", 0.056, 0.332), ("Unigram", 0.796, 0.302), ("日", 0.836, 0.302), ("Reach Captain Level10", 0.105, 0.392),
    ("θ Chaos", 0.579, 0.375), ("Partners", 0.791, 0.375), ("方舟城市", 0.571, 0.463), ("Storage", 0.790, 0.451), ("Combatants", 0.565, 0.552),
    ("Achievement", 0.808, 0.520), ("Archive", 0.790, 0.594), ("EVENT", 0.519, 0.639), ("营救", 0.584, 0.639), ("Shop", 0.781, 0.666),
    ("N", 0.816, 0.666), ("?", 0.963, 0.706), ("10d 23h", 0.056, 0.870), ("31d 23h", 0.618, 0.832), ("Reach Captain Level 10", 0.104, 0.925),
    ("Upon theSnW", 0.586, 0.925), ("APromrse=", 0.593, 0.885),
)
# 273, the open menu with its key labels on: `End` under the power button.
MENU_KEYS = MENU + (("ESC", 0.962, 0.076), ("M", 0.962, 0.310), ("O", 0.962, 0.815), ("End", 0.964, 0.951))
# 218, the Notice board over the Lobby.
NOTICE = (
    ("Notice", 0.216, 0.119), ("Update", 0.403, 0.119), ("of being my partner for tonight Captain.", 0.325, 0.26), ("I shall allow you the honor", 0.324, 0.215),
    ("Distress Signal", 0.692, 0.267), ("Amplified", 0.662, 0.211), ("Blazebell", 0.66, 0.323), ("Distress Signal:", 0.692, 0.473), ("Amplified", 0.663, 0.419),
    ("Vivian", 0.642, 0.534), ("NightmarexCarnival", 0.716, 0.656), ("Attire & Card Skin Release!", 0.327, 0.736),
    ("Visit the Official Website", 0.717, 0.725), ("Go Now", 0.325, 0.826), ("Ongoing", 0.652, 0.854),
)
# 217, the entry banner: no text that stays from one banner to the next.
BANNER = (("Seasonal", 0.132, 0.766), ("Rossweisse", 0.184, 0.827), ("Seasonal Combatant Rescue Rate-Up", 0.234, 0.906), ("11d 0h", 0.48, 0.905))
# 274, the Mail screen with three mails to claim.
MAIL = (
    ("√", 0.068, 0.089), ("Mail", 0.107, 0.090), ("003 / 100", 0.844, 0.090), ("1st Anniversary Login Rewards hav..", 0.265, 0.183),
    ("From. Chaos Zero Nightmare", 0.217, 0.244), ("区 6d 23h", 0.410, 0.244), ("1st Anniversary Login Rewards have arrived!", 0.698, 0.215),
    ("From. Chaos Zero Nightmare", 0.611, 0.257), ("2026-10-2807:00", 0.884, 0.260), ("N", 0.047, 0.298), ("+", 0.929, 0.288),
    ("1st Anniversary Surprise Growth S..", 0.262, 0.329), ("From. Chaos Zero Nightmare", 0.216, 0.392), ("区 6d 23h", 0.409, 0.391),
    ("We've prepared a special gift to celebrate our 1st Anniversary", 0.716, 0.378), ("N", 0.047, 0.446), ("together with our Protos.", 0.599, 0.411),
    ("Make sure to claim it now!", 0.603, 0.441), ("1st Anniversary Login Rewards hav...", 0.264, 0.478), ("From. Chaos Zero Nightmare", 0.217, 0.541),
    ("区 6d 23h", 0.410, 0.541), ("①", 0.061, 0.902), ("Claim All", 0.194, 0.904), ("Delete read mail", 0.380, 0.905), ("Claim", 0.850, 0.867),
)
# 276, the same mail after Claim All: OCR read `Claim AIl`, and the open mail's Claim has turned into Delete.
MAIL_AFTER = tuple(box for box in MAIL if box[0] not in ("√", "①", "Claim All", "Claim", "N")) + (
    ("静", 0.099, 0.242), ("Claim AIl", 0.194, 0.905), ("Delete", 0.851, 0.868),
)
# 522, the empty mailbox's popup on a live run: it reads as 276, Claim All greyed. A press on it shows the toast here.
MAIL_EMPTY = MAIL_AFTER
MAIL_TOAST = MAIL_AFTER + (("All items in the mail have been received.", 0.500, 0.275),)
# 275, Items Obtained over the Mail screen.
ITEMS = (
    ("Items Obtained", 0.502, 0.377), ("365,000", 0.287, 0.568), ("2,000", 0.384, 0.568), ("5", 0.487, 0.566), ("365", 0.566, 0.568),
    ("V", 0.499, 0.885), ("点击屏幕关闭窗口", 0.501, 0.935), ("进入", 0.500, 0.978),
)
# The daily attendance popup on day 4, opened as the Mail popup closed: days 1 to 3 stamped, today's Claim Reward, the
# X drawn but not read. Then Items Obtained over it, and the popup again with day 4 stamped and its X read.
ATTENDANCE = (
    ("Invitation to a New Journey", 0.690, 0.169), ("Permanent", 0.833, 0.229), ("02", 0.541, 0.308), ("1", 0.629, 0.318), ("03", 0.653, 0.307),
    ("07", 0.778, 0.325), ("04", 0.431, 0.611), ("05", 0.542, 0.612), ("06", 0.653, 0.611), ("Claim Reward", 0.459, 0.830),
    ("Awaiting Attendance", 0.571, 0.831), ("Awaiting Attendance", 0.683, 0.831), ("Awaiting Attendance", 0.817, 0.828),
)
ATTENDANCE_ITEMS = (("Items Obtained", 0.502, 0.377), ("点击屏幕关闭窗口", 0.501, 0.935), ("进入", 0.500, 0.977))
ATTENDANCE_STAMPED = (
    ("Invitation to a New Journey", 0.690, 0.169), ("X", 0.933, 0.127), ("Permanent", 0.833, 0.229), ("02", 0.541, 0.309), ("03", 0.653, 0.307),
    ("07", 0.778, 0.326), ("天", 0.568, 0.450), ("04", 0.428, 0.612), ("05", 0.542, 0.612), ("06", 0.653, 0.611),
    ("Awaiting Attendance", 0.571, 0.831), ("Awaiting Attendance", 0.683, 0.831), ("Awaiting Attendance", 0.817, 0.828),
)
# 264, the Lobby a few idle seconds later, its UI faded out: OCR reads nothing.
FADED = ()
# A live start's faded Lobby: only the character's speech bubble reads.
FADED_BUBBLE = (("oh, I was writing a poem. t's my hobby.", 0.258, 0.278),)
# Where the faded-scene crops sit: x 0-441 and y 21-302 of a 1080p capture.
SCENE_REGION = (0.0, 0.02, 0.23, 0.28)
# Claim All's crops, from 274 (orange) and the live run's empty popup (greyed): x 57-480 and y 928-1026.
CLAIM_ALL_CROP = (0.03, 0.86, 0.25, 0.95)
# 222, the Selective Rescue screen, and 253, a paid Rescue's Crystal dialog.
RESCUE = (
    ("√", 0.041, 0.043), ("营救", 0.116, 0.048), ("235", 0.71, 0.048), ("Skip Tutorial", 0.88, 0.054), ("Special Signal Selective Rescue", 0.386, 0.255),
    ("Shop", 0.109, 0.922), ("Rescue Info", 0.253, 0.926), ("Selective Rescue 10 time(s)", 0.849, 0.912), ("免费", 0.95, 0.912),
)
PAID_RESCUE = (
    ("营救", 0.115, 0.047), ("235", 0.709, 0.048), ("10 Signal Amplification Anchor required.", 0.502, 0.423),
    ("Spend 1600 Crystals to make the purchase?", 0.500, 0.463), ("取消", 0.347, 0.631), ("确认", 0.667, 0.631), ("Rescue 10 time(s)", 0.848, 0.913),
)
# The Event list as the menu's Event opens it, on its first event rather than Dream Park; and the same list without Dream Park.
EVENT_LIST = (
    ("√", 0.041, 0.046), ("Event", 0.109, 0.048), ("N", 0.973, 0.030), ("↓ Recommended Events", 0.091, 0.138), ("N", 0.215, 0.111),
    ("Invitation to a New Journey", 0.774, 0.136), ("Event Description", 0.784, 0.201), ("Permanent", 0.918, 0.201),
    ("tation to a New Journey", 0.114, 0.270), ("02", 0.626, 0.335), ("03", 0.738, 0.336), ("kie Captain Mission", 0.101, 0.395),
    ("07", 0.861, 0.353), ("le Path of a Captain", 0.102, 0.519), ("N", 0.179, 0.576), ("htmare Dream Park", 0.100, 0.644), ("04", 0.512, 0.636),
    ("05", 0.625, 0.636), ("06", 0.737, 0.636), ("nise Upon the Snow", 0.101, 0.771), ("Awaiting Attendance", 0.543, 0.854),
    ("Awaiting Attendance", 0.656, 0.854), ("Awaiting Attendance", 0.768, 0.855), ("Awaiting Attendance", 0.901, 0.854),
    ("Poised Against the(", 0.103, 0.894),
)
EVENT_LIST_WITHOUT_PARK = tuple(box for box in EVENT_LIST if "Dream Park" not in box[0])
# The Lobby while the Nightmare Carnival runs, its banner read at (0.101, 0.396).
LOBBY_CARNIVAL = (
    ('22', 0.055, 0.09), ('等级', 0.054, 0.049), ('N', 0.136, 0.032), ('240/240+', 0.698, 0.049), ('★', 0.778, 0.056),
    ('E', 0.835, 0.048), ('0%', 0.103, 0.084), ('F2', 0.836, 0.077), ('F3', 0.898, 0.076), ('Q', 0.959, 0.076), ('故事', 0.884, 0.156),
    ('Act', 0.744, 0.195), ('1-Chapter 2, Episode 2', 0.838, 0.194), ('0/1', 0.064, 0.262), ('1 time(s) at the Ark City Rese', 0.147, 0.234),
    ('Sortie', 0.884, 0.266), ('O7d 9h', 0.046, 0.332), ('Simulation', 0.874, 0.353), ('Nightmare Carnival', 0.101, 0.396), ('N', 0.048, 0.439),
    ('Chaos', 0.891, 0.442), ('F4', 0.036, 0.5), ('Awaiting policies 3', 0.854, 0.555), ('方舟城市', 0.883, 0.521), ('Combatants', 0.868, 0.617),
    ('EVENT', 0.822, 0.704), ('营救', 0.887, 0.703), ('N', 0.049, 0.736), ('·C4>', 0.898, 0.73), ('28d 9h', 0.936, 0.832), ('Blazebell', 0.148, 0.925),
    ('Rate up', 0.162, 0.892), ('UpontheSnW', 0.889, 0.925), ('APromrse', 0.894, 0.887),
)
# The Carnival on Attendance Check with days 3 to 5 pending; Items Obtained after one press on day 3; every reached
# day claimed; the Exchange tab, its `Go` opening the shop.
CARNIVAL = (
    ('Nightmare Carnival', 0.169, 0.047), ('N', 0.973, 0.031), ('Nightmare Carnival Guide', 0.109, 0.168), ('Attendance', 0.795, 0.165),
    ('Check', 0.929, 0.164), ('Event Description', 0.827, 0.229), ('7d 9h', 0.943, 0.231),
    ("Captain! You'll come visit the Nightmare Carnival", 0.805, 0.282), ('every day, right?', 0.916, 0.317), ('Attendance Check', 0.108, 0.369),
    ('Check-In Make-Up', 0.811, 0.398), ('Exchange', 0.109, 0.545), ('6', 0.705, 0.508), ('14', 0.951, 0.516), ('Parade', 0.109, 0.719),
    ('Welcome Gift', 0.109, 0.894),
)
CARNIVAL_AFTER = (
    ('Nightmare Carnival', 0.169, 0.047), ('N', 0.973, 0.031), ('Nightmare Carnival Guide', 0.109, 0.166), ('Attendance', 0.795, 0.165),
    ('Check', 0.928, 0.163), ('Event Description', 0.827, 0.229), ('7d gh', 0.943, 0.231),
    ("Captain! You'll come visit the Nightmare Carnival", 0.805, 0.282), ('every day, right?', 0.916, 0.317), ('Attendance Check', 0.109, 0.369),
    ('Check-In Make-Up', 0.811, 0.398), ('Exchange', 0.109, 0.543), ('6', 0.705, 0.508), ('L', 0.952, 0.516), ('Parade', 0.109, 0.719),
    ('2', 0.448, 0.726), ('Welcome Gift', 0.109, 0.894), ('+01110+', 0.781, 0.882),
)
CARNIVAL_ITEMS = (
    ('Items Obtained', 0.502, 0.377), ('点击屏幕关闭窗口', 0.501, 0.934), ('进入', 0.5, 0.977),
)
CARNIVAL_EXCHANGE = (
    ('Nightmare Carnival', 0.169, 0.048), ('N', 0.972, 0.029), ('个Nightmare Carnival Guide θ', 0.109, 0.168), ('Exchange', 0.906, 0.169),
    ('Event Description', 0.827, 0.231), ('7d 9h', 0.943, 0.231), ('Attendance Check', 0.109, 0.369), ('05', 0.651, 0.331), ('06', 0.805, 0.327),
    ('07', 0.959, 0.33), ('02', 0.356, 0.416), ('03', 0.43, 0.416), ('04', 0.505, 0.415), ('-', 0.75, 0.409), ('Exchange', 0.109, 0.544),
    ('2', 0.279, 0.619), ('1st Nightmare Card', 0.607, 0.671), ('[Partner]', 0.606, 0.701), ('1st Nightmare Card', 0.76, 0.673),
    ('Parade', 0.109, 0.72), ('GEENE', 0.397, 0.707), ('[Combatant]', 0.759, 0.7), ('300-1000', 0.297, 0.782), ('-2000-4000', 0.433, 0.783),
    ('7000', 0.603, 0.782), ('10000', 0.76, 0.782), ('15000', 0.915, 0.783), ('Until Next Reward', 0.474, 0.846), ('0/300', 0.643, 0.846),
    ('Go', 0.954, 0.845), ('Welcome Gift', 0.11, 0.894),
    ('* When purchasing products eligible for [Nightmare Tokens], [Nightmare Tokens] will be sent via in-game mail along with the', 0.605, 0.906),
    ('product.', 0.603, 0.933), ('If event rewards have been claimed, refunds for the purchased product may be restricted.', 0.604, 0.962),
)
# Where the Carnival crops were cut: the day bars under the cards, x 384-1920 and y 918-1004 of a 1080p capture.
CARNIVAL_CROP = (0.20, 0.85, 1.0, 0.93)
# The Path of a Captain with the Lv 20 tier ready; Items Obtained after its claim; the tier claimed; and the same on a
# client whose list no longer has Dream Park.
CAPTAIN = (
    ('Event', 0.108, 0.047), ('N', 0.972, 0.03), ('→ Recommended Events', 0.091, 0.138), ('N', 0.214, 0.111),
    ('The Path of a Captain', 0.823, 0.166), ('ritation to a New Jol', 0.101, 0.27), ('Event Description', 0.791, 0.232),
    ('O Permanent', 0.924, 0.231), ('achieve outstanding results deserve rewards fitting their', 0.773, 0.315),
    ('Captains who lead the charge in exploring Chaos and', 0.784, 0.281), ('efforts. Build your expertise as a captain and earn', 0.798, 0.349),
    ('okie Captain Missio', 0.102, 0.395), ('generous rewards.', 0.909, 0.385), ('Current Level 22', 0.91, 0.458),
    ('The Path of aCaptain', 0.11, 0.519), ('?', 0.605, 0.514), ('N', 0.179, 0.576), ('ghtmare Dream Parl', 0.101, 0.644), ('LEVEL', 0.302, 0.617),
    ('10', 0.303, 0.658), ('20', 0.453, 0.659), ('LEVEL', 0.452, 0.616), ('30', 0.604, 0.66), ('LEVEL', 0.604, 0.618), ('40', 0.756, 0.658),
    ('LEVEL', 0.755, 0.618), ('50', 0.906, 0.657), ('LEVEL', 0.906, 0.617), ('Promise Upon the S', 0.099, 0.77), ('15', 0.651, 0.813),
    ('10', 0.739, 0.813), ('20', 0.802, 0.813), ('10', 0.891, 0.813), ('20', 0.954, 0.813), ('ade Poised Against 1', 0.101, 0.894),
    ('Claimed', 0.302, 0.913), ('Claim Reward', 0.453, 0.914), ('Insufficient level', 0.605, 0.914), ('Insufficient level', 0.755, 0.914),
    ('Insufficient level', 0.906, 0.914), ('N', 0.178, 0.95),
)
CAPTAIN_ITEMS = (
    ('Items Obtained', 0.502, 0.377), ('5', 0.486, 0.566), ('10', 0.573, 0.567), ('V', 0.499, 0.887), ('点击屏幕关闭窗口', 0.501, 0.935), ('进入', 0.5, 0.979),
)
CAPTAIN_AFTER = (
    ('Event', 0.108, 0.047), ('N', 0.972, 0.03), ('→ Recommended Events', 0.091, 0.138), ('N', 0.214, 0.111),
    ('The Path of a Captain', 0.823, 0.166), ('n to a New Journey', 0.099, 0.27), ('Event Description', 0.791, 0.231), ('O Permanent', 0.924, 0.231),
    ('achieve outstanding results deserve rewards fitting their', 0.773, 0.315),
    ('Captains who lead the charge in exploring Chaos and', 0.786, 0.281), ('efforts. Build your expertise as a captain and earn', 0.799, 0.35),
    ('kie Captain Mission', 0.101, 0.394), ('generous rewards.', 0.909, 0.385), ('Current Level 22', 0.91, 0.458),
    ('The Path of aCaptain', 0.11, 0.519), ('N', 0.179, 0.576), ('htmare Dream Park', 0.101, 0.644), ('LEVEL', 0.302, 0.617), ('10', 0.303, 0.658),
    ('20', 0.453, 0.658), ('LEVEL', 0.453, 0.617), ('30', 0.604, 0.66), ('LEVEL', 0.604, 0.618), ('40', 0.755, 0.658), ('LEVEL', 0.755, 0.618),
    ('50', 0.907, 0.659), ('LEVEL', 0.906, 0.618), ('lise Upon the Snow', 0.101, 0.771), ('15', 0.651, 0.813), ('10', 0.739, 0.813),
    ('20', 0.802, 0.813), ('10', 0.891, 0.813), ('20', 0.953, 0.813), ('d Against the Cycle', 0.101, 0.894), ('Claimed', 0.302, 0.913),
    ('Claimed', 0.454, 0.913), ('Insufficient level', 0.605, 0.914), ('Insufficient level', 0.755, 0.914), ('Insufficient level', 0.906, 0.914),
    ('-', 0.104, 0.958), ('N', 0.178, 0.95),
)
CAPTAIN_WITHOUT_PARK = tuple(box for box in CAPTAIN_AFTER if "Dream Park" not in box[0])
# 266, the Graphic Settings page, a screen Daily has no business on.
SETTINGS = (
    ("Graphic Settings", 0.184, 0.091), (":X", 0.932, 0.091), ("Graphics", 0.138, 0.172), ("Image Quality", 0.161, 0.233), ("High", 0.797, 0.234),
    ("Game Resolution", 0.173, 0.307), ("1920×1080", 0.808, 0.304), ("Screen Mode", 0.161, 0.378), ("Full Screen", 0.796, 0.376),
    ("Reset", 0.680, 0.892), ("Apply", 0.917, 0.894),
)

# 474, the Lobby during the tutorial: its Skip Tutorial pill covers the Menu point. The player's name is left out.
TUTORIAL_LOBBY = (
    ("等级", 0.055, 0.049), ("08", 0.057, 0.090), ("N", 0.137, 0.032), ("240/240+", 0.698, 0.050), ("⭐", 0.776, 0.053), ("E1", 0.777, 0.077),
    ("Skip Tutorial", 0.879, 0.054), ("23%", 0.107, 0.085), ("Oh my. Do you need training? Great", 0.235, 0.170),
    ("Act 1-Chapter 1, Episode 8", 0.824, 0.194), ("故事", 0.884, 0.157), ("Sortie", 0.885, 0.267), ("Simulation", 0.876, 0.352),
    ("Chaos", 0.891, 0.442), ("方舟城市", 0.876, 0.530), ("Combatants", 0.868, 0.617), ("EVENT", 0.823, 0.704), ("营救", 0.886, 0.705),
)
SKIP_TUTORIAL = ("Skip Tutorial", 0.879, 0.055)
# The pill's outline on every capture of it, which a tap anywhere inside presses.
SKIP_TUTORIAL_PILL = (0.818, 0.020, 0.992, 0.091)

# The Activity window and the Achievement screen, from a live run's captures.
# 1077, the Activity window on Growth Guide 02: three cards read Claim Reward, a fourth is cut at the right edge.
GUIDE_READY = (
    ("Growth Guide", 0.171, 0.112), ("Growth Guide", 0.164, 0.219), ("02", 0.361, 0.250), ("2. Project Reboot", 0.463, 0.219), ("0/7", 0.408, 0.253),
    ("G", 0.702, 0.282), ("300", 0.825, 0.284), ("7", 0.057, 0.340), ("Clear Story", 0.345, 0.499), ("Chapter2.EP", 0.357, 0.536),
    ("Approve policies 1", 0.569, 0.499), ("times in Ark City", 0.561, 0.537), ("Order coffee 1 time", 0.760, 0.500),
    ("at the Ark City", 0.743, 0.538), ("Raise an", 0.922, 0.500), ('"Ark City"', 0.340, 0.575), ("[GardenCafé]", 0.744, 0.574),
    ("Combate", 0.922, 0.536), ("level 20", 0.919, 0.575), ("111", 0.319, 0.619), ("111", 0.708, 0.619), ("3/3", 0.905, 0.619), ("200", 0.354, 0.772),
    ("40,000", 0.420, 0.771), ("200", 0.549, 0.772), ("6", 0.633, 0.771), ("200", 0.744, 0.772), ("6", 0.829, 0.771), ("200", 0.940, 0.772),
    ("Claim Reward", 0.391, 0.854), ("Claim Reward", 0.584, 0.854), ("Claim Reward", 0.780, 0.854), ("①", 0.898, 0.854), ("Clai", 0.934, 0.853),
)
# 1199, Growth Guide 03 with no card finished: every card reads Move.
GUIDE_MOVE = (
    ("Growth Guide", 0.172, 0.111), ("1", 0.057, 0.231), ("Growth Guide", 0.164, 0.218), ("03", 0.361, 0.248),
    ("3. The Leader's Principle", 0.491, 0.219), ("6/10", 0.413, 0.251), ("+0110", 0.872, 0.245), ("300", 0.825, 0.285), ("7", 0.057, 0.340),
    ("the Ark City", 0.348, 0.537), ("Learn 1 time(s) at", 0.371, 0.499), ("Clear Story Chapter", 0.561, 0.499), ("Research Facility", 0.368, 0.575),
    ('2.#07"Operation:', 0.557, 0.535), ('Saving Wolf Platoon"', 0.566, 0.574), ("Chapter2.EP", 0.746, 0.536), ("Clear Story", 0.737, 0.499),
    ("Clear Batl", 0.923, 0.499), ('"EpioneCenter"', 0.754, 0.572), ("Chapter 2", 0.923, 0.538), ("Promotiol", 0.923, 0.574), ("0/1", 0.319, 0.619),
    ("0/1", 0.514, 0.619), ("0/1", 0.709, 0.620), ("0/1", 0.905, 0.619), ("300", 0.354, 0.771), ("20", 0.433, 0.770), ("300", 0.549, 0.772),
    ("40", 0.629, 0.771), ("300", 0.744, 0.772), ("20", 0.824, 0.770), ("300", 0.940, 0.772), ("D", 0.312, 0.852), ("Move", 0.421, 0.853),
    ("D", 0.508, 0.852), ("Move", 0.617, 0.853), ("D", 0.704, 0.852), ("Move", 0.811, 0.853), ("D", 0.898, 0.852),
)
# 1126, Growth Guide 02 with every card claimed, its stage ring orange.
GUIDE_DONE = (
    ("Growth Guide", 0.171, 0.111), ("1", 0.056, 0.231), ("Growth Guide", 0.163, 0.217), ("02", 0.362, 0.249), ("2.Project Reboot", 0.463, 0.219),
    ("717", 0.408, 0.252), ("2", 0.703, 0.283), ("5", 0.768, 0.285), ("300", 0.823, 0.285), ("Chapter2.EP", 0.355, 0.536),
    ("Clear Story", 0.346, 0.498), ("Complete 1", 0.538, 0.498), ('"Ark City"', 0.340, 0.574), ("an Agent in Ark City", 0.568, 0.575),
    ("Excursion(s) with", 0.560, 0.537), ("times in Ark City", 0.756, 0.537), ("Approve policies 1", 0.765, 0.499), ("at the Ark", 0.922, 0.536),
    ("Order cof", 0.923, 0.499), ("[Garden (", 0.923, 0.573), ("1/1", 0.318, 0.619), ("1/1", 0.514, 0.619), ("1/1", 0.708, 0.619),
    ("1/1", 0.905, 0.619), ("200", 0.353, 0.770), ("40,000", 0.420, 0.770), ("200", 0.548, 0.771), ("200", 0.743, 0.771), ("6", 0.828, 0.771),
    ("200", 0.939, 0.771), ("V", 0.316, 0.853), ("Complete", 0.405, 0.854), ("Complete", 0.600, 0.854), ("Complete", 0.796, 0.853),
)
# 1128, Growth Guide 03 right after the stage reward, three cards already finished.
GUIDE_NEXT_STAGE = (
    ("Growth Guide", 0.171, 0.112), ("1", 0.058, 0.231), ("Growth Guide", 0.164, 0.218), ("03", 0.361, 0.249),
    ("3. The Leader's Principle", 0.491, 0.219), ("0/10", 0.414, 0.253), ("0+0110+", 0.872, 0.245), ("300", 0.825, 0.284), ("7", 0.057, 0.340),
    ("Complete", 0.336, 0.499), ("[Potential]", 0.340, 0.535), ("Partner(s) to level", 0.567, 0.535), ("Raise any 3", 0.542, 0.499),
    ("Clear Battle", 0.738, 0.498), ("20", 0.510, 0.575), ("MissionChapter", 0.757, 0.537), ("Clear Sin", 0.922, 0.499),
    ("Simulation3 time(s)", 0.372, 0.574), ("2.B6", 0.713, 0.573), ("15 time(≤", 0.923, 0.537), ("3/3", 0.320, 0.620), ("3/3", 0.515, 0.620),
    ("111", 0.708, 0.619), ("15/15", 0.913, 0.620), ("300", 0.354, 0.771), ("300", 0.549, 0.772), ("300", 0.744, 0.772), ("6", 0.829, 0.771),
    ("300", 0.940, 0.771), ("Claim Reward", 0.391, 0.854), ("Claim Reward", 0.583, 0.854), ("Claim Reward", 0.781, 0.854), ("①", 0.898, 0.852),
    ("Clair", 0.934, 0.853),
)
# 1200, the daily schedule with reached tiers, Claim All orange, read as `Claim AIl`.
SCHEDULE = (
    ("Achievement schedule", 0.206, 0.112), ("O22h until Daily Schedule resets", 0.787, 0.108), ("n", 0.066, 0.202), ("20", 0.327, 0.237),
    ("Order 1 time(s) at the café", 0.602, 0.215), ("10", 0.396, 0.274), ("300", 0.453, 0.274), ("0/1", 0.516, 0.288), ("D", 0.908, 0.250),
    ("20", 0.853, 0.288), ("40", 0.327, 0.388), ("Use 120 Aether", 0.560, 0.372), ("人", 0.061, 0.435), ("300", 0.454, 0.425),
    ("100/ 120", 0.532, 0.443), ("D", 0.908, 0.406), ("40", 0.853, 0.447), ("60", 0.327, 0.538), ("time(s)", 0.528, 0.565),
    ("Successfully Ravage monsters 3", 0.626, 0.529), ("10", 0.396, 0.574), ("300", 0.454, 0.574), ("……", 0.907, 0.562), ("2/3", 0.517, 0.600),
    ("40", 0.853, 0.602), ("Today's schedule complete", 0.193, 0.654), ("Schedule Progress", 0.190, 0.696), ("80", 0.327, 0.688),
    ("Log into the game", 0.570, 0.687), ("300", 0.454, 0.724), ("1/1", 0.515, 0.755), ("20", 0.852, 0.755), ("①", 0.129, 0.837),
    ("Claim AIl", 0.226, 0.838), ("100", 0.321, 0.837), ("Go on Ark City Excursions 1 time(s)", 0.637, 0.839), ("20", 0.395, 0.873),
    ("300", 0.454, 0.874), ("EHENFT", 0.949, 0.965),
)
# 1202, the daily schedule after its claim, Claim All grey.
SCHEDULE_AFTER = (
    ("Achievement schedule", 0.206, 0.112), ("O22h until Daily Schedule resets", 0.787, 0.108), ("PP", 0.055, 0.203), ("1", 0.055, 0.226),
    ("20", 0.327, 0.237), ("Order 1 time(s) at the café", 0.602, 0.216), ("300", 0.453, 0.273), ("0/1", 0.516, 0.288), ("20", 0.853, 0.289),
    ("7", 0.056, 0.340), ("40", 0.326, 0.387), ("Use 120 Aether", 0.560, 0.372), ("300", 0.454, 0.424), ("100/ 120", 0.533, 0.442),
    ("D", 0.908, 0.406), ("40", 0.853, 0.446), ("60", 0.327, 0.538), ("time(s)", 0.528, 0.564), ("Successfully Ravage monsters 3", 0.626, 0.529),
    ("300", 0.453, 0.574), ("2/3", 0.516, 0.601), ("……", 0.907, 0.562), ("40", 0.853, 0.602), ("Today's schedule complete", 0.192, 0.653),
    ("Schedule Progress", 0.190, 0.696), ("80", 0.327, 0.687), ("Log into the game", 0.571, 0.687), ("300", 0.454, 0.723), ("1/1", 0.515, 0.755),
    ("20", 0.852, 0.756), ("①", 0.130, 0.834), ("Claim All", 0.225, 0.838), ("100", 0.322, 0.837), ("300", 0.453, 0.873),
    ("Go on Ark City Excursions 1 time(s)", 0.637, 0.839), ("20", 0.395, 0.870), ("EHENFT", 0.949, 0.965),
)
# 1317, the weekly schedule with one goal reading Goal Achieved, the milestones claimed.
WEEKLY_GOAL = (
    ("Weekly Schedule", 0.184, 0.112), ("①21h 34m until Weekly Schedule resets", 0.765, 0.108), ("1", 0.056, 0.227), ("15", 0.394, 0.255),
    ("200", 0.449, 0.255), ("15", 0.535, 0.255), ("200", 0.590, 0.254), ("15", 0.665, 0.248), ("200", 0.731, 0.255), ("15", 0.814, 0.256),
    ("200", 0.871, 0.256), ("100", 0.406, 0.303), ("200", 0.546, 0.303), ("400", 0.687, 0.303), ("600", 0.827, 0.303), ("7", 0.056, 0.340),
    ("G", 0.178, 0.344), ("0", 0.405, 0.335), ("0", 0.545, 0.335), ("Weekly Schedule Progress", 0.174, 0.516), ("the café", 0.334, 0.549),
    ("Order 2 time(s) at", 0.372, 0.509), ("Aether", 0.524, 0.511), ("220/1000", 0.176, 0.560), ("Consumption: 640", 0.569, 0.549),
    ("Approve Ark City", 0.760, 0.511), ("Policies 10 time(s)", 0.764, 0.550), ("Schedule", 0.924, 0.549), ("Cumulati", 0.924, 0.511),
    ("Progress", 0.923, 0.588), ("212", 0.320, 0.641), ("460/640", 0.532, 0.642), ("3/10", 0.714, 0.642), ("200/400", 0.923, 0.643),
    ("Operation Disks Owned", 0.176, 0.710), ("400", 0.225, 0.764), ("100", 0.352, 0.781), ("100", 0.549, 0.782), ("100", 0.744, 0.782),
    ("100", 0.940, 0.783), ("Mission Records Shop", 0.188, 0.845), ("Goal Achieved", 0.388, 0.869), ("Move", 0.615, 0.868), ("D", 0.703, 0.867),
    ("Move", 0.811, 0.868),
)
# 1319, the same after the goal: the card has left the row and the progress rose from 220 to 320.
WEEKLY_AFTER = (
    ("I Weekly Schedule", 0.184, 0.111), ("①21h 34m until Weekly Schedule resets", 0.765, 0.108), ("1", 0.056, 0.227), ("15", 0.394, 0.256),
    ("200", 0.449, 0.255), ("15", 0.535, 0.255), ("200", 0.590, 0.255), ("15", 0.665, 0.248), ("200", 0.731, 0.255), ("15", 0.814, 0.256),
    ("200", 0.871, 0.256), ("100", 0.406, 0.303), ("200", 0.546, 0.303), ("400", 0.687, 0.303), ("0", 0.404, 0.335), ("600", 0.827, 0.302),
    ("7", 0.057, 0.341), ("0", 0.546, 0.336), ("Weekly Schedule Progress", 0.174, 0.516), ("Consumption: 640", 0.373, 0.547),
    ("Aether", 0.330, 0.511), ("Policies 10 time(s)", 0.568, 0.549), ("Approve Ark City", 0.564, 0.511), ("320/1000", 0.176, 0.560),
    ("Schedule", 0.731, 0.549), ("Cumulative Daily", 0.758, 0.510), ("Total log", 0.923, 0.512), ("Progress: 400", 0.747, 0.586),
    ("460/640", 0.336, 0.640), ("3 /10", 0.519, 0.642), ("200/400", 0.727, 0.642), ("3/4", 0.906, 0.642), ("Operation Disks Owned", 0.176, 0.710),
    ("400", 0.225, 0.764), ("✨", 0.729, 0.742), ("100", 0.351, 0.780), ("100", 0.548, 0.782), ("100", 0.744, 0.782), ("100", 0.940, 0.783),
    ("Mission Records Shop", 0.188, 0.844), ("D", 0.311, 0.867), ("Move", 0.420, 0.868), ("D", 0.506, 0.866), ("Move", 0.615, 0.868),
    ("D", 0.703, 0.868), ("Move", 0.811, 0.869), ("……", 0.899, 0.867), ("In", 0.947, 0.870),
)
# 709, the weekly schedule with the 100 and 200 milestones reached and unclaimed.
WEEKLY_MILESTONES = (
    ("I Weekly Schedule", 0.184, 0.111), ("① 1d 3h until Weekly Schedule resets", 0.774, 0.108), ("1", 0.056, 0.227), ("-200", 0.449, 0.254),
    ("5", 0.521, 0.246), ("-200", 0.588, 0.254), ("5", 0.665, 0.248), ("200", 0.731, 0.255), ("15", 0.814, 0.256), ("200", 0.871, 0.256),
    ("10", 0.407, 0.317), ("200", 0.546, 0.302), ("0-", 0.548, 0.334), ("400", 0.687, 0.302), ("600", 0.827, 0.302), ("7", 0.057, 0.340),
    ("Weekly Schedule Progress", 0.174, 0.516), ("the café", 0.334, 0.549), ("Order 2 time(s) at", 0.372, 0.509), ("Aether", 0.525, 0.509),
    ("Consumption: 640", 0.569, 0.548), ("Approve Ark City", 0.760, 0.511), ("220/1000", 0.176, 0.560), ("Policies 10 time(s)", 0.764, 0.549),
    ("Schedule", 0.924, 0.549), ("Cumulati", 0.924, 0.511), ("Progress", 0.923, 0.588), ("0/2", 0.320, 0.641), ("240/640", 0.532, 0.642),
    ("0/ 10", 0.713, 0.642), ("100/400", 0.922, 0.643), ("Operation Disks Owned", 0.176, 0.710), ("0", 0.235, 0.765), ("✨", 0.534, 0.741),
    ("100", 0.352, 0.781), ("100", 0.549, 0.782), ("100", 0.744, 0.782), ("100", 0.940, 0.783), ("Mission Records Shop", 0.188, 0.844),
    ("D", 0.311, 0.867), ("Move", 0.420, 0.868), ("Move", 0.615, 0.868), ("D", 0.703, 0.868), ("Move", 0.811, 0.869),
)
# 711, the same after one milestone press took both tiers.
WEEKLY_CLAIMED = (
    ("I Weekly Schedule", 0.184, 0.111), ("① 1d 3h until Weekly Schedule resets", 0.774, 0.108), ("15", 0.394, 0.256), ("200", 0.449, 0.255),
    ("15", 0.535, 0.255), ("200", 0.590, 0.254), ("15", 0.665, 0.248), ("200", 0.731, 0.255), ("15", 0.814, 0.256), ("200", 0.871, 0.256),
    ("100", 0.406, 0.303), ("200", 0.546, 0.303), ("0", 0.404, 0.335), ("0", 0.545, 0.335), ("400", 0.687, 0.302), ("600", 0.827, 0.302),
    ("7", 0.057, 0.341), ("Weekly Schedule Progress", 0.174, 0.516), ("the café", 0.334, 0.549), ("Order 2 time(s) at", 0.372, 0.509),
    ("Aether", 0.525, 0.511), ("Consumption: 640", 0.569, 0.548), ("Approve Ark City", 0.760, 0.511), ("220/1000", 0.176, 0.560),
    ("Policies 10 time(s)", 0.764, 0.549), ("Schedule", 0.924, 0.549), ("Cumulati", 0.924, 0.511), ("Progress", 0.923, 0.588), ("0/2", 0.320, 0.641),
    ("240/640", 0.532, 0.642), ("0/ 10", 0.713, 0.642), ("100/400", 0.922, 0.643), ("Operation Disks Owned", 0.176, 0.710), ("400", 0.225, 0.764),
    ("✨", 0.534, 0.741), ("100", 0.352, 0.781), ("100", 0.549, 0.782), ("100", 0.744, 0.782), ("100", 0.940, 0.783),
    ("Mission Records Shop", 0.188, 0.845), ("D", 0.311, 0.867), ("Move", 0.420, 0.868), ("Move", 0.615, 0.868), ("Move", 0.811, 0.869),
)
# 790, the Achievement Log, its top row ready and the rows below not.
LOG = (
    ("|Achievement Log", 0.182, 0.112), ("1", 0.056, 0.227), ("16", 0.273, 0.305), ("等级", 0.271, 0.276), ("8", 0.460, 0.330), ("8", 0.532, 0.331),
    ("40", 0.599, 0.331), ("20", 0.670, 0.331), ("17", 0.272, 0.441), ("X", 0.508, 0.431), ("……", 0.800, 0.438), ("1", 0.390, 0.480),
    ("8", 0.460, 0.481), ("8", 0.531, 0.481), ("40", 0.600, 0.481), ("20", 0.669, 0.481), ("18", 0.272, 0.606), ("等级", 0.272, 0.575),
    ("5", 0.389, 0.631), ("8", 0.460, 0.631), ("8", 0.531, 0.631), ("40", 0.599, 0.630), ("20", 0.670, 0.631), ("19", 0.272, 0.756),
    ("等级", 0.272, 0.725), ("……", 0.801, 0.739), ("8", 0.460, 0.780), ("8", 0.532, 0.781), ("40", 0.598, 0.780), ("20", 0.670, 0.779),
)
# 714, the Achievement Log after its claim.
LOG_AFTER = (
    ("| Achievement Log", 0.184, 0.112), ("1", 0.056, 0.225), ("等级", 0.272, 0.275), ("………", 0.800, 0.289), ("7", 0.057, 0.340), ("1", 0.389, 0.329),
    ("8", 0.460, 0.330), ("8", 0.531, 0.331), ("40", 0.599, 0.331), ("20", 0.670, 0.330), ("等级", 0.271, 0.424), ("17", 0.272, 0.454),
    ("X", 0.508, 0.431), ("1", 0.390, 0.480), ("8", 0.460, 0.481), ("8", 0.531, 0.481), ("40", 0.600, 0.481), ("20", 0.670, 0.481),
    ("18", 0.272, 0.606), ("等级", 0.272, 0.575), ("……", 0.800, 0.589), ("5", 0.390, 0.631), ("8", 0.460, 0.631), ("8", 0.532, 0.631),
    ("40", 0.599, 0.631), ("20", 0.669, 0.631), ("19", 0.272, 0.756), ("等级", 0.272, 0.724), ("……", 0.801, 0.739), ("8", 0.460, 0.781),
    ("8", 0.532, 0.781), ("40", 0.598, 0.780), ("20", 0.669, 0.779), ("EHEnFI", 0.948, 0.965),
)
# 1424, the Achievement Log with Lv 19 ready, the Lv 22 label read as `$22$`.
LOG_LV19 = (
    ("|Achievement Log", 0.182, 0.113), ("00", 0.657, 0.260), ("1", 0.390, 0.329), ("8", 0.460, 0.330), ("8", 0.532, 0.331), ("40", 0.600, 0.332),
    ("20", 0.670, 0.330), ("20", 0.272, 0.443), ("2", 0.390, 0.481), ("12", 0.459, 0.481), ("6", 0.532, 0.482), ("6", 0.603, 0.482),
    ("1", 0.674, 0.482), ("200,000", 0.724, 0.481), ("Simulation Stage 3 unlocks upon clearing the promotion mission", 0.441, 0.542),
    ("Intermediate Captain", 0.743, 0.543), ("21", 0.272, 0.670), ("等级", 0.271, 0.638), ("……", 0.799, 0.653), ("6", 0.390, 0.695),
    ("6", 0.461, 0.695), ("10", 0.528, 0.693), ("5", 0.603, 0.694), ("1", 0.674, 0.694), ("200,000", 0.723, 0.694), ("$22$", 0.272, 0.805),
    ("…", 0.800, 0.802), ("1", 0.390, 0.843), ("6", 0.532, 0.844), ("10", 0.599, 0.844), ("5", 0.673, 0.844), ("1", 0.745, 0.844),
    ("EPEnFi", 0.947, 0.965),
)
# The weekly schedule with two goals achieved; after one press took both, tiers 100 and 200 reached; Items Obtained
# after one press took both tiers; both tiers ticked. The Achievement Log with levels 20, 21 and 22 ready (20 read as
# `2ǔ`), and after one press took all three.
WEEKLY_TWO_GOALS = (
    ('Weekly Schedule', 0.184, 0.112), ('①5d 4h until Weekly Schedule resets', 0.774, 0.108), ('1', 0.056, 0.225), ('15', 0.394, 0.256),
    ('200', 0.451, 0.255), ('100', 0.406, 0.301), ('15', 0.523, 0.248), ('200', 0.59, 0.255), ('15', 0.665, 0.249), ('200', 0.731, 0.255),
    ('15', 0.814, 0.256), ('200', 0.872, 0.256), ('200', 0.546, 0.302), ('400', 0.687, 0.303), ('600', 0.827, 0.303), ('7', 0.057, 0.34),
    ('G', 0.178, 0.344), ('Weekly Schedule Progress', 0.174, 0.516), ('Total login days: 1', 0.374, 0.512), ('0/1000', 0.176, 0.56),
    ('time(s)', 0.525, 0.546), ('Clear Chaos 2', 0.553, 0.511), ('the café', 0.726, 0.55), ('Order 2 time(s) at', 0.762, 0.511),
    ('Consuml', 0.923, 0.55), ('Aether', 0.916, 0.512), ('1/1', 0.318, 0.641), ('212', 0.515, 0.642), ('0/2', 0.71, 0.641),
    ('240/ 640', 0.922, 0.642), ('Operation Disks Owned', 0.176, 0.71), ('400', 0.225, 0.764), ('✨', 0.534, 0.741), ('100', 0.353, 0.78),
    ('120', 0.549, 0.779), ('100', 0.744, 0.782), ('100', 0.94, 0.783), ('Mission Records Shop', 0.188, 0.845), ('Goal Achieved', 0.388, 0.869),
    ('Goal Achieved', 0.584, 0.869), ('Move', 0.811, 0.868),
)
WEEKLY_TWO_TIERS = (
    ('I Weekly Schedule', 0.184, 0.111), ('①5d 4h until Weekly Schedule resets', 0.774, 0.108), ('1', 0.056, 0.226), ('15', 0.394, 0.256),
    ('-200', 0.449, 0.254), ('10', 0.407, 0.317), ('5', 0.521, 0.246), ('-200', 0.589, 0.254), ('5', 0.665, 0.248), ('200', 0.731, 0.255),
    ('15', 0.814, 0.256), ('200', 0.871, 0.256), ('200', 0.546, 0.302), ('0-', 0.548, 0.334), ('400', 0.687, 0.302), ('600', 0.827, 0.302),
    ('7', 0.057, 0.34), ('Weekly Schedule Progress', 0.174, 0.516), ('the café', 0.334, 0.549), ('Order 2 time(s) at', 0.372, 0.509),
    ('Aether', 0.525, 0.511), ('Consumption: 640', 0.569, 0.548), ('Approve Ark City', 0.76, 0.511), ('220/1000', 0.176, 0.56),
    ('Policies 10 time(s)', 0.764, 0.549), ('Schedule', 0.924, 0.549), ('Cumulati', 0.924, 0.511), ('Progress', 0.923, 0.588), ('0/2', 0.32, 0.641),
    ('240/640', 0.532, 0.642), ('0/ 10', 0.713, 0.642), ('100/400', 0.922, 0.643), ('Operation Disks Owned', 0.176, 0.71), ('400', 0.225, 0.764),
    ('✨', 0.534, 0.741), ('100', 0.352, 0.781), ('100', 0.549, 0.782), ('100', 0.744, 0.782), ('100', 0.94, 0.783),
    ('Mission Records Shop', 0.188, 0.845), ('D', 0.311, 0.867), ('Move', 0.42, 0.868), ('Move', 0.615, 0.868), ('D', 0.703, 0.867),
    ('Move', 0.811, 0.869), ('D', 0.895, 0.867),
)
MILESTONE_ITEMS = (
    ('Items Obtained', 0.502, 0.377), ('30', 0.483, 0.567), ('400', 0.566, 0.568), ('V', 0.5, 0.885), ('点击屏幕关闭窗口', 0.501, 0.935), ('进入', 0.5, 0.977),
)
WEEKLY_TIERS_TAKEN = (
    ('I Weekly Schedule', 0.184, 0.111), ('①5d 4h until Weekly Schedule resets', 0.774, 0.108), ('1', 0.057, 0.226), ('15', 0.394, 0.256),
    ('200', 0.449, 0.255), ('15', 0.535, 0.255), ('200', 0.59, 0.254), ('15', 0.665, 0.248), ('200', 0.731, 0.255), ('15', 0.814, 0.256),
    ('200', 0.871, 0.256), ('100', 0.406, 0.303), ('200', 0.546, 0.303), ('0', 0.404, 0.335), ('0', 0.545, 0.335), ('400', 0.687, 0.302),
    ('600', 0.827, 0.302), ('Weekly Schedule Progress', 0.174, 0.516), ('the café', 0.334, 0.549), ('Order 2 time(s) at', 0.372, 0.509),
    ('Aether', 0.525, 0.511), ('Consumption: 640', 0.569, 0.548), ('Approve Ark City', 0.76, 0.511), ('220/1000', 0.176, 0.56),
    ('Policies 10 time(s)', 0.764, 0.549), ('Schedule', 0.924, 0.549), ('Cumulati', 0.924, 0.511), ('Progress', 0.923, 0.588), ('口', 0.031, 0.639),
    ('0/2', 0.32, 0.641), ('240/640', 0.532, 0.642), ('0/ 10', 0.713, 0.642), ('100/400', 0.922, 0.643), ('Operation Disks Owned', 0.176, 0.71),
    ('800', 0.225, 0.764), ('✨', 0.534, 0.741), ('100', 0.352, 0.781), ('100', 0.549, 0.782), ('100', 0.744, 0.782), ('100', 0.94, 0.783),
    ('Mission Records Shop', 0.188, 0.844), ('D', 0.311, 0.867), ('Move', 0.42, 0.868), ('Move', 0.615, 0.868), ('D', 0.703, 0.867),
    ('Move', 0.811, 0.868),
)
LOG_THREE = (
    ('|Achievement Log', 0.182, 0.113), ('2ǔ', 0.272, 0.292), ('6', 0.531, 0.331), ('6', 0.603, 0.331), ('200,000', 0.723, 0.332),
    ('Simulation Stage 3 unlocks upon clearing the promotion mission', 0.433, 0.393), ('Intermediate Captain', 0.736, 0.393), ('21', 0.271, 0.506),
    ('6', 0.39, 0.544), ('6', 0.46, 0.544), ('10', 0.528, 0.544), ('5', 0.603, 0.544), ('1', 0.673, 0.543), ('200,000', 0.723, 0.544),
    ('22', 0.272, 0.655), ('1', 0.389, 0.693), ('18', 0.457, 0.694), ('6', 0.532, 0.695), ('10', 0.598, 0.693), ('5', 0.673, 0.695),
    ('1', 0.745, 0.695), ('$2\\$', 0.272, 0.805), ('……', 0.8, 0.801), ('6', 0.46, 0.844), ('6', 0.532, 0.844), ('6', 0.602, 0.844),
    ('10', 0.67, 0.844), ('5', 0.745, 0.844),
)
LOG_THREE_TAKEN = (
    ('|Achievement Log', 0.182, 0.112), ('23', 0.272, 0.292), ('…', 0.799, 0.288), ('7', 0.057, 0.339), ('1', 0.39, 0.331), ('6', 0.461, 0.331),
    ('6', 0.532, 0.331), ('6', 0.603, 0.331), ('10', 0.67, 0.331), ('5', 0.745, 0.331), ('24', 0.272, 0.455), ('等级', 0.272, 0.424),
    ('…', 0.799, 0.438), ('18', 0.385, 0.48), ('6', 0.461, 0.481), ('6', 0.532, 0.481), ('10', 0.598, 0.48), ('5', 0.673, 0.481),
    ('200,000', 0.724, 0.481), ('25', 0.272, 0.606), ('等级', 0.272, 0.575), ('300', 0.382, 0.631), ('5', 0.461, 0.631), ('18', 0.53, 0.631),
    ('16', 0.601, 0.631), ('12', 0.671, 0.631), ('250,000', 0.724, 0.631), ('26', 0.272, 0.756), ('等级', 0.272, 0.724), ('D', 0.508, 0.731),
    ('16', 0.456, 0.779), ('16', 0.529, 0.781), ('16', 0.599, 0.781), ('16', 0.669, 0.78), ('8', 0.745, 0.781),
)
# Where the weekly and log crops were cut: both goal cards, the milestone labels, and the log's claim column.
GOALS_CROP = (0.30, 0.84, 0.66, 0.90)
LOG_COLUMN_CROP = (0.77, 0.22, 0.83, 0.97)
# 972, the Achievement screen's four category cards.
ACHIEVEMENT_CARDS = (
    ("Achievement", 0.143, 0.048), ("1", 0.907, 0.037), ("Journey Log", 0.141, 0.689), ("Exploration", 0.381, 0.674), ("Attitude", 0.379, 0.703),
    ("Obliteration", 0.619, 0.705), ("Traces of", 0.620, 0.673), ("Overcoming", 0.858, 0.674), ("8/53", 0.141, 0.742), ("Adversity", 0.857, 0.706),
    ("4 /58", 0.381, 0.743), ("2/81", 0.620, 0.743), ("24/ 108", 0.859, 0.743), ("Completed Achievements", 0.349, 0.902), ("38", 0.467, 0.903),
    ("2211", 0.562, 0.904), ("💖４", 0.657, 0.902), ("ş1", 0.716, 0.903),
)
# 973, Journey Log open, four rows ready and Claim All blue.
CATEGORY_JOURNEY = (
    ("Achievement", 0.143, 0.045), ("3,803", 0.840, 0.047), ("😜", 0.973, 0.030), ("Journey Log", 0.105, 0.138), ("Journey Log", 0.376, 0.130),
    ("…Progress", 0.370, 0.200), ("8/53", 0.561, 0.199), ("①", 0.828, 0.165), ("Claim All", 0.910, 0.163), ("Exploration Attitude", 0.111, 0.220),
    ("Traces of Obliteration", 0.113, 0.302), ("Chaos Zero", 0.339, 0.313), ("Begin the Chaos Zero operation.", 0.392, 0.356), ("WGTD", 0.668, 0.338),
    ("Overcoming Adversity", 0.110, 0.387), ("Claim Reward", 0.896, 0.344), ("(First game login)", 0.346, 0.388), ("5", 0.776, 0.389),
    ("Loss", 0.309, 0.485), ("Clear Story - A Promise Unkept.", 0.391, 0.526), ("2", 0.833, 0.519), ("Claim Reward", 0.896, 0.514),
    ("10", 0.772, 0.558), ("Black Rose", 0.335, 0.656), ("Completed [Story] Eye of the Storm", 0.404, 0.695), ("Claim Reward", 0.895, 0.684),
    ("10", 0.772, 0.727), ("If it comes to that again", 0.388, 0.823), ("Complete Story - A Promise Renewed", 0.410, 0.865), ("V", 0.833, 0.858),
    ("Claim Reward", 0.896, 0.853), ("10", 0.772, 0.896), ("Achievement Condions|J", 0.097, 0.941), ("Possible Return to Duty", 0.389, 0.986),
)
# 1206, Journey Log open with nothing ready, Claim All grey.
CATEGORY_JOURNEY_DONE = (
    ("Achievement", 0.143, 0.045), ("4,554", 0.840, 0.047), ("Λ", 0.972, 0.027), ("Journey Log", 0.091, 0.137), ("Journey Log", 0.376, 0.131),
    ("Exploratin Atitude", 0.099, 0.220), ("……Progress", 0.370, 0.201), ("8/53", 0.561, 0.199), ("Claim All", 0.910, 0.160),
    ("Traces of Obliteration", 0.111, 0.304), ("A Correctable Mistake", 0.383, 0.314), ("XOvercoming Adversity", 0.098, 0.388),
    ("[Story] Complete City of Outlaws", 0.397, 0.356), ("0/1", 0.887, 0.345), ("10", 0.773, 0.389), ("Rally Complete!", 0.355, 0.485),
    ("[story] Complete Operation: Saving Wolf Platoon", 0.447, 0.525), ("0/1", 0.887, 0.516), ("10", 0.773, 0.558), ("Wolf's Requiem", 0.355, 0.656),
    ("Complete Story - We Are Wolf Platoon!", 0.414, 0.694), ("0/1", 0.887, 0.683), ("10", 0.772, 0.727), ("Pilgrimage", 0.334, 0.825),
    ("[Story] Complete Holy City Haven", 0.398, 0.864), ("0/1", 0.887, 0.853), ("10", 0.775, 0.897), ("AchievementCondions|J", 0.097, 0.941),
    ("Devour", 0.320, 0.987),
)
# 978, Overcoming Adversity open after its claim, Claim All grey.
CATEGORY_OVERCOMING_DONE = (
    ("√", 0.041, 0.045), ("Achievement", 0.143, 0.046), ("4,143", 0.841, 0.048), ("😜", 0.973, 0.030), ("Journey Log", 0.092, 0.137),
    ("Overcoming Adversity", 0.428, 0.131), ("……Progress", 0.369, 0.200), ("24./108", 0.553, 0.199), ("①", 0.829, 0.159), ("Claim All", 0.910, 0.160),
    ("Exploratin Atitude", 0.099, 0.220), ("Traces of Obliteration", 0.111, 0.302), ("Wise man", 0.330, 0.314),
    ("XOovercomingAdverityy", 0.095, 0.388), ("Awaken 100 Signature Cards through Epiphanies", 0.446, 0.356), ("85/ 100", 0.887, 0.344),
    ("10", 0.773, 0.389), ("I Choose my Own Path", 0.385, 0.485), ("Transform cards via Epiphany 50 times", 0.414, 0.525), ("12/50", 0.887, 0.515),
    ("5", 0.776, 0.559), ("Prophet of Fate", 0.354, 0.655), ("Transform cards via Epiphany 100 times", 0.418, 0.694), ("12 / 100", 0.887, 0.684),
    ("10", 0.772, 0.727), ("Full Speed Ahead with a Heart on Fire", 0.448, 0.825), ("Destroy Chaos Cores 5 times with only Passion", 0.441, 0.865),
    ("0/5", 0.887, 0.854), ("combatants on your team", 0.371, 0.895), ("5", 0.778, 0.896), ("Achievement Condions|J", 0.097, 0.941),
    ("Please Eollow the Rules", 0.389, 0.987),
)
# 1078, Items Obtained over the Activity window after a Growth Guide claim.
CLAIM_ITEMS = (
    ("Items Obtained", 0.502, 0.377), ("200", 0.478, 0.568), ("40,000", 0.554, 0.568), ("点击屏幕关闭窗口", 0.501, 0.935), ("进入", 0.500, 0.977),
)
# The open categories without the capture for each: the heading names the category, Claim All grey.
CATEGORY_EXPLORATION_DONE = tuple(("Exploration Attitude", x, y) if (name, x) == ("Journey Log", 0.376) else (name, x, y) for name, x, y in CATEGORY_JOURNEY_DONE)
CATEGORY_TRACES_DONE = tuple(("Traces of Obliteration", x, y) if (name, x) == ("Journey Log", 0.376) else (name, x, y) for name, x, y in CATEGORY_JOURNEY_DONE)
CATEGORY_EXPLORATION = tuple(("Exploration Attitude", x, y) if (name, x) == ("Journey Log", 0.376) else (name, x, y) for name, x, y in CATEGORY_JOURNEY)
CATEGORY_TRACES = tuple(("Traces of Obliteration", x, y) if (name, x) == ("Journey Log", 0.376) else (name, x, y) for name, x, y in CATEGORY_JOURNEY)
CATEGORY_OVERCOMING = tuple(("Overcoming Adversity", x, y) if (name, x) == ("Journey Log", 0.376) else (name, x, y) for name, x, y in CATEGORY_JOURNEY)
# Where each patch of those captures was cut, as `(left, top, right, bottom)` fractions of a 1080p capture.
STAGE_CROP = (0.85, 0.21, 0.90, 0.28)
SCHEDULE_CROP = (0.11, 0.80, 0.31, 0.88)
GOAL_CROP = (0.30, 0.84, 0.47, 0.90)
MILESTONES_CROP = (0.37, 0.28, 0.86, 0.33)
LOG_CROP = (0.78, 0.26, 0.82, 0.47)
CATEGORY_CROP = (0.83, 0.13, 0.98, 0.20)
# The Activity window's rows 0.15 apart: the Achievement Log's second row cut 0.15 higher lands where the top row is read.
LOG_ROW = 0.15

# Where each target sits, written out here rather than read from the module, so a point drifting there fails a test.
POINTS = {
    daily.BANNER_CLOSE: (0.968, 0.049),
    daily.NOTICE_CLOSE: (0.911, 0.120),
    daily.MENU: (0.959, 0.046),
    daily.ENVELOPE: (0.962, 0.280),
    daily.MENU_CLOSE: (0.961, 0.049),
    daily.MAIL_CLOSE: (0.936, 0.093),
    daily.WAKE: (0.300, 0.420),
    daily.CLAIM_ALL: (0.194, 0.904),
    daily.ITEMS_CLOSE: (0.501, 0.935),
    daily.EVENT: (0.783, 0.088),
    daily.DREAM_PARK: (0.100, 0.644),
    daily.EVENT_LEAVE: (0.041, 0.046),
    daily.ENTER_PARK: (0.775, 0.901),
    daily.PARK_ACHIEVEMENTS: (0.551, 0.900),
    daily.PAGE_LEAVE: (0.041, 0.046),
    daily.PARK_MANAGE: (0.087, 0.294),
    daily.PARK_OPERATE: (0.087, 0.473),
    daily.PANEL_CLOSE: (0.041, 0.046),
    daily.PARK_LEAVE: (0.041, 0.046),
    daily.PARK_RANK: (0.804, 0.906),
    daily.RANK_UP: (0.502, 0.900),
    daily.RANK_CLOSE: (0.977, 0.137),
    daily.RANK_RESULT_CLOSE: (0.500, 0.938),
    daily.UPGRADE: (0.772, 0.634),
    daily.BUILD: (0.761, 0.845),
    daily.CLAIM: (0.722, 0.166),
    daily.MANAGEMENT_TAB: (0.100, 0.270),
    daily.ACHIEVEMENTS_LEAVE: (0.041, 0.046),
    daily.RULES_CANCEL: (0.347, 0.631),
    daily.PROFIT_CLOSE: (0.500, 0.938),
    daily.STORY_SKIP: (0.767, 0.053),
    daily.SKIP_TICK: (0.392, 0.532),
    daily.SKIP_CONFIRM: (0.667, 0.631),
    daily.ATTENDANCE_CLAIM: (0.459, 0.830),
    daily.ATTENDANCE_CLOSE: (0.933, 0.127),
    daily.SKILL_TAB: (0.892, 0.185),
    daily.FACILITIES_TAB: (0.714, 0.185),
    daily.SKILL_UPGRADE: (0.772, 0.456),
    daily.HAPPY_DAY_UPGRADE: (0.772, 0.847),
    daily.ACTIVITY: (0.789, 0.231),
    daily.GUIDE_TAB: (0.057, 0.120),
    daily.SCHEDULE_TAB: (0.057, 0.231),
    daily.WEEKLY_TAB: (0.057, 0.340),
    daily.LOG_TAB: (0.057, 0.680),
    daily.ACTIVITY_CLOSE: (0.940, 0.115),
    daily.GUIDE_CLAIM: (0.391, 0.854),
    daily.STAGE_CLAIM: (0.873, 0.247),
    daily.SCHEDULE_CLAIM: (0.226, 0.838),
    daily.GOAL_CLAIM: (0.388, 0.869),
    daily.MILESTONE_CLAIM: (0.405, 0.220),
    daily.LOG_CLAIM: (0.800, 0.290),
    daily.ACHIEVEMENT_ENTRY: (0.808, 0.520),
    daily.JOURNEY_CARD: (0.141, 0.600),
    daily.CATEGORY_TABS[0]: (0.111, 0.138),
    daily.CATEGORY_TABS[1]: (0.111, 0.220),
    daily.CATEGORY_TABS[2]: (0.111, 0.302),
    daily.CATEGORY_TABS[3]: (0.111, 0.387),
    daily.CATEGORY_CLAIM: (0.910, 0.163),
    daily.CARDS_LEAVE: (0.041, 0.046),
    daily.CATEGORY_LEAVE: (0.041, 0.046),
    daily.CARNIVAL_BANNER: (0.101, 0.396),
    daily.CARNIVAL_TAB: (0.120, 0.330),
    daily.CARNIVAL_DAY: (0.305, 0.885),
    daily.CARNIVAL_LEAVE: (0.041, 0.046),
    daily.CAPTAIN_ENTRY: (0.102, 0.519),
    daily.CAPTAIN_CLAIM: (0.453, 0.914),
    daily.INVEST_ENTRY: (0.867, 0.617),
    daily.UNIT_CARD: (0.324, 0.330),
    daily.LIST_LEAVE: (0.041, 0.046),
    daily.DETAILS_LEAVE: (0.041, 0.046),
    daily.STATS_TAB: (0.121, 0.258),
    daily.PARTNERS_TAB: (0.133, 0.444),
    daily.POTENTIAL_TAB: (0.134, 0.631),
    daily.OPEN_PROMOTION: (0.861, 0.921),
    daily.OPEN_LEVEL_UP: (0.861, 0.921),
    daily.PARTNER_UPGRADE: (0.804, 0.924),
    daily.PROMOTE: (0.859, 0.919),
    daily.AUTO_REGISTER: (0.852, 0.835),
    daily.LEVEL_UP: (0.859, 0.920),
    daily.PANEL_LEAVE: (0.041, 0.046),
    daily.NODE_01_ENTRY: (0.309, 0.814),
    daily.NODE_02_ENTRY: (0.442, 0.835),
    daily.ACTIVATE: (0.860, 0.920),
    daily.NODE_LEAVE: (0.041, 0.046),
    daily.RESULT_CLOSE: (0.500, 0.938),
}
# What Daily must never press, by where it sits. Power is the icon's centre in 265 (rows 972-1022 of 1080) and the
# `End` key label under it in 273. Skip Tutorial is a box over three targets, not a point: `TestTutorial` covers it.
NEVER = {
    "Delete read mail": (0.380, 0.905),
    "the open mail's Claim, then Delete": (0.850, 0.867),
    "the Aether +": (0.70, 0.05),
    "the Lobby's Rescue": (0.887, 0.705),
    "Go Now": (0.325, 0.826),
    "Visit the Official Website": (0.717, 0.725),
    "the banner's dots": (0.944, 0.050),
    "the Notice board's dots": (0.889, 0.119),
    "the film icon": (0.843, 0.12),
    "the menu's Shop": (0.781, 0.666),
    "the menu's Arkhianon Supply": (0.825, 0.160),
    "the menu's settings": (0.962, 0.813),
    "the menu's power": (0.962, 0.923),
    "the power's End label": (0.962, 0.949),
    "Items Obtained's 进入": (0.500, 0.978),
    "the Mail popup's dots": (0.912, 0.093),
    "the Mail popup's envelope": (0.068, 0.089),
    "a day still awaiting attendance": (0.571, 0.831),
    "the attendance popup's dots": (0.932, 0.159),
    "the Activity window's fourth tab": (0.057, 0.450),
    "the Activity window's fifth tab": (0.057, 0.570),
    "a Growth Guide card's Move": (0.421, 0.853),
    "the Growth Guide card cut at the right edge": (0.934, 0.853),
    "the daily schedule's play arrow": (0.908, 0.406),
    "the Mission Records Shop": (0.188, 0.844),
    "a weekly goal's Move": (0.615, 0.868),
    "the Carnival's Check-In Make-Up": (0.811, 0.398),
    "the Carnival's Make-Up +": (0.940, 0.400),
    "the Carnival Exchange's Go": (0.954, 0.845),
    "the Carnival's Exchange tab": (0.120, 0.500),
    "the Carnival's Parade tab": (0.120, 0.700),
    "the Carnival's Welcome Gift tab": (0.120, 0.880),
    "the Carnival's home": (0.898, 0.046),
    "a claimed Path of a Captain tier": (0.302, 0.913),
    "a Path of a Captain tier still locked": (0.605, 0.914),
}
# How close a tap may come to a point before it counts as pressing it: about 19 px across and 11 px down at 1080p. The
# banner's dots sit 0.015 left of where the Lobby's Menu is tapped, but only on the banner, where Daily taps the X instead.
NEAR = 0.01

# Daily's own handlers in the order they must run, which the shape test holds the module to.
OWN = (
    spend_guard.handle_rescue_screen,
    daily.handle_daily_tutorial,
    daily.handle_daily_overtime,
    daily.handle_daily_items_obtained,
    daily.handle_daily_attendance,
    daily.handle_daily_mail,
    daily.handle_daily_activity,
    daily.handle_daily_achievement_category,
    daily.handle_daily_achievement_cards,
    daily.handle_daily_carnival,
    daily.handle_daily_rules_dialog,
    daily.handle_daily_profit_report,
    daily.handle_daily_skip_dialog,
    daily.handle_daily_park_story,
    daily.handle_daily_rank_result,
    daily.handle_daily_rank_screen,
    daily.handle_daily_manage_panel,
    daily.handle_daily_facilities,
    daily.handle_daily_skill_tab,
    daily.handle_daily_park_view,
    daily.handle_daily_park_achievements,
    daily.handle_daily_event_page,
    daily.handle_daily_captain_page,
    daily.handle_daily_event_list,
    daily.handle_daily_invest_card,
    daily.handle_daily_invest_promotion,
    daily.handle_daily_invest_level,
    daily.handle_daily_invest_node,
    daily.handle_daily_invest_stats,
    daily.handle_daily_invest_partners,
    daily.handle_daily_invest_map,
    daily.handle_daily_invest_list,
    daily.handle_daily_notice,
    daily.handle_daily_banner,
    daily.handle_daily_lobby_menu,
    daily.handle_daily_lobby,
    daily.handle_daily_faded_lobby,
    daily.handle_daily_unknown_screen,
)
# Upstream's generic handlers: a Lobby stop that would end Daily on its first frame, blind taps and a centred Confirm.
FORBIDDEN = ("handle_non_battle_page", "handle_center_confirm", "handle_stuck_log", "handle_enter", "handle_confirm")
# Taken at import, before any test's install can reach the module's list.
PRISTINE = list(daily.PAGE_HANDLERS)


def corner(name):
    """Put a capture's top-right corner back into an otherwise black frame.

    Args:
        name: The crop's base name in `tests/images/`, cut at x 1728-1920 and y 0-130 of a 1080p capture.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    patch = cv2.imread(str(REPO_ROOT / "tests" / "images" / f"{name}.png"))
    frame[:patch.shape[0], WIDTH - patch.shape[1]:] = patch
    return frame


def placed(name, region):
    """Put a crop of a capture back where it was cut, into an otherwise black frame.

    Args:
        name: The crop's base name in `tests/images/`.
        region: Where it was cut, as `(left, top, right, bottom)` fractions of a 1080p capture.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    patch = cv2.imread(str(REPO_ROOT / "tests" / "images" / f"{name}.png"))
    left, top = int(region[0] * WIDTH), int(region[1] * HEIGHT)
    frame[top:top + patch.shape[0], left:left + patch.shape[1]] = patch
    return frame


def faded_lobby(name="daily_faded_lobby"):
    """Give a faded Lobby's frame: 272 by default, `daily_faded_lobby_character` for 352, whose character still stands."""
    return placed(name, SCENE_REGION)


def claim_all(lit):
    """Give a Mail frame's Claim All: orange from 274 when lit, greyed from the live run's empty popup when not."""
    return placed("daily_claim_all_lit" if lit else "daily_claim_all_greyed", CLAIM_ALL_CROP)


def composed(*crops):
    """Put several crops of captures back where each was cut, into one otherwise black frame.

    Args:
        crops: `(name, region)` pairs, as `placed` takes them.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for name, region in crops:
        frame = np.maximum(frame, placed(name, region))
    return frame


# Each Activity tab and achievement category with nothing ready, on the greyed patches, each shown long enough to settle.
GUIDE_NOTHING = (GUIDE_MOVE, placed("activity_stage_ring_greyed", STAGE_CROP))
SCHEDULE_NOTHING = (SCHEDULE_AFTER, placed("activity_schedule_greyed", SCHEDULE_CROP))
WEEKLY_NOTHING = (WEEKLY_CLAIMED, composed(("activity_goal_gone", GOAL_CROP), ("activity_milestones_claimed", MILESTONES_CROP)))
LOG_NOTHING = (LOG_AFTER, placed("activity_log_claimed", LOG_CROP))
CATEGORIES_NOTHING = ((CATEGORY_JOURNEY_DONE, placed("achievement_claim_all_greyed_journey", CATEGORY_CROP)),
                      (CATEGORY_EXPLORATION_DONE, placed("achievement_claim_all_greyed", CATEGORY_CROP)),
                      (CATEGORY_TRACES_DONE, placed("achievement_claim_all_greyed", CATEGORY_CROP)),
                      (CATEGORY_OVERCOMING_DONE, placed("achievement_claim_all_greyed", CATEGORY_CROP)))
SETTLED = daily.SETTLE + 1
# The chores before the park.
BEFORE_PARK = ("mail", "activity", "achievement", "carnival")
# The two claim chores from the open menu with nothing ready, back to the Lobby, whose Menu is pressed for the park. Only
# the tabs, the card and the exits are pressed.
NOTHING_TO_CLAIM = ([MENU] + [GUIDE_NOTHING] * SETTLED + [SCHEDULE_NOTHING] * SETTLED + [WEEKLY_NOTHING] * SETTLED + [LOG_NOTHING] * SETTLED
                    + [LOBBY, MENU, ACHIEVEMENT_CARDS] + [screen for screen in CATEGORIES_NOTHING for _ in range(SETTLED)] + [ACHIEVEMENT_CARDS, LOBBY])
NOTHING_TO_CLAIM_PRESSES = (daily.ACTIVITY, daily.SCHEDULE_TAB, daily.WEEKLY_TAB, daily.LOG_TAB, daily.ACTIVITY_CLOSE, daily.MENU,
                            daily.ACHIEVEMENT_ENTRY, daily.JOURNEY_CARD, *daily.CATEGORY_TABS[1:], daily.CATEGORY_LEAVE, daily.CARDS_LEAVE, daily.MENU)
# The park step from the open menu on a client whose Event list no longer has Dream Park: The Path of a Captain is
# opened first, with nothing ready, then the list is left.
NO_PARK_ROUTE = [MENU, EVENT_LIST_WITHOUT_PARK] + [CAPTAIN_WITHOUT_PARK] * SETTLED
NO_PARK_ROUTE_PRESSES = (daily.EVENT, daily.CAPTAIN_ENTRY, daily.EVENT_LEAVE)


class Clock:
    """Monotonic time the test moves by hand."""

    def __init__(self):
        self.now = START

    def monotonic(self):
        return self.now


class Executor:
    """Finds the app's modes by class name, as ok-script's executor does, and carries its PostMessage input."""

    def __init__(self, *tasks):
        self.tasks = list(tasks)
        self.interaction = mock.Mock(spec=PostMessageInteraction)

    def get_task_by_class_name(self, name):
        return next((task for task in self.tasks if type(task).__name__ == name), None)


class Task:
    """Daily looking at one screen, recording every tap, drag, announcement and stop."""

    width, height = WIDTH, HEIGHT

    def __init__(self):
        self.name = "Daily"
        self.all_texts = []
        self.frame = None
        self.enabled = True
        self.clicks = []
        self.waits = []
        self.zones = []
        self.zone_read = list
        self.swipes = []
        self.logged = []
        self.notifications = []
        self.disabled = 0
        self.executor = Executor(self)

    def show(self, texts, frame=None):
        """Put a screen in front of Daily.

        Args:
            texts: `(name, x, y)` triples, placed as fractions of the screen.
            frame: The capture, or None.

        Returns:
            The task.
        """
        self.all_texts = [FakeBox(name, x, y) for name, x, y in texts]
        self.frame = frame
        return self

    def move_relative(self, x, y):
        pass

    def sleep(self, seconds):
        pass

    def click(self, x, y, after_sleep=0):
        self.clicks.append((x, y))
        self.waits.append(after_sleep)

    def ocr(self, x, y, to_x, to_y):
        """Read a zone of the screen with `zone_read`, which reads nothing unless a test says otherwise."""
        self.zones.append((x, y, to_x, to_y))
        return self.zone_read()

    def swipe_relative(self, from_x, from_y, to_x, to_y, duration=0.5, settle_time=0):
        self.swipes.append((from_x, from_y, to_x, to_y, duration))

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.disabled += 1
        self.enabled = False
        vars(self).pop(daily.RUN, None)


def second_bottom_button(task):
    """Match Claim All loosely, as the bottom bar's second button from the left, which on the Mail screen is `Delete read mail`."""
    bottom = sorted((box for box in task.all_texts if box.y > 0.85 * HEIGHT and box.x < 0.5 * WIDTH), key=lambda box: box.x)
    return bottom[1]


def run_pass(task):
    """Run Daily's handlers once over the screen, as its run loop does.

    Returns:
        True when a handler claimed the frame.
    """
    return any(handler(task) for handler in OWN)


class Daily(unittest.TestCase):

    def setUp(self):
        self.clock = Clock()
        patcher = mock.patch.object(daily, "time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        # A screen Daily stops on without knowing it is saved, so no test may reach the real `logs/unknown`.
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.unknown_folder = Path(root.name) / "logs" / "unknown"
        patcher = mock.patch.object(daily, "UNKNOWN_FOLDER", self.unknown_folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.task = Task()

    def tick(self, seconds=1):
        self.clock.now += seconds

    def state(self):
        return daily.run_state(self.task)

    def finish_chores(self, mail="claimed"):
        """Count every chore as done, the mail with what it found."""
        steps = self.state()["steps"]
        for step in steps:
            steps[step] = daily.DONE
        self.state()["mail"] = mail

    def to_park(self):
        """Count the chores before the park as done, the mail claimed, and The Path of a Captain as not in the Event list."""
        steps = self.state()["steps"]
        for step in BEFORE_PARK:
            steps[step] = daily.DONE
        self.state()["mail"] = "claimed"
        self.state()["claims"]["captain"] = "not listed"

    def assertPressed(self, *targets):
        """Check the taps were exactly these targets, in order."""
        self.assertEqual(len(targets), len(self.task.clicks), self.task.clicks)
        for (x, y), target in zip(self.task.clicks, targets):
            expected = POINTS[target]
            self.assertAlmostEqual(expected[0], x, delta=0.005, msg=target)
            self.assertAlmostEqual(expected[1], y, delta=0.005, msg=target)

    def assertNothingForbidden(self):
        for x, y in self.task.clicks:
            for name, (never_x, never_y) in NEVER.items():
                self.assertFalse(abs(x - never_x) < NEAR and abs(y - never_y) < NEAR, f"pressed {name} at ({x:.3f}, {y:.3f})")

    def assertStopped(self, message_part):
        self.assertEqual(1, self.task.disabled)
        self.assertEqual(1, len(self.task.notifications), self.task.notifications)
        self.assertIn(message_part, self.task.notifications[0])


class TestMail(Daily):

    def test_after_the_claim_nothing_reading_delete_is_pressed_and_only_the_x_once_claimed(self):
        """1: the open mail's Claim turns into Delete in place, and `Delete read mail` sits 0.19 right of Claim All."""
        self.assertTrue(run_pass(self.task.show(MAIL_AFTER)))
        self.assertPressed(daily.CLAIM_ALL)
        self.task.clicks.clear()
        self.state()["steps"]["mail"] = daily.DONE
        self.assertTrue(run_pass(self.task.show(MAIL_AFTER)))
        self.assertPressed(daily.MAIL_CLOSE)
        self.assertNothingForbidden()

    def test_claim_all_is_pressed_once_waited_on_then_retried_once_and_a_third_press_refused(self):
        """2: a second frame inside the wait presses nothing, and the press limit refuses a third."""
        self.task.show(MAIL)
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.CLAIM_ALL)
        for _ in range(daily.CLAIM_WAIT - 1):
            self.tick()
            self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.CLAIM_ALL)
        self.tick()
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.CLAIM_ALL, daily.CLAIM_ALL)
        self.assertTrue(daily.press(self.task, daily.CLAIM_ALL, daily.claim_all_button(self.task)))
        self.assertPressed(daily.CLAIM_ALL, daily.CLAIM_ALL)
        self.assertStopped("Claim All was pressed 2 times")

    def test_claim_all_that_opens_nothing_twice_counts_as_no_mail_and_closes(self):
        self.task.show(MAIL)
        for _ in range(2 * daily.CLAIM_WAIT + 1):
            run_pass(self.task)
            self.tick()
        self.assertPressed(daily.CLAIM_ALL, daily.CLAIM_ALL, daily.MAIL_CLOSE)
        self.assertEqual("nothing to claim", self.state()["mail"])
        self.assertEqual(0, self.task.disabled)

    def test_a_mail_screen_without_claim_all_is_waited_on_before_it_counts_as_empty(self):
        """OCR can miss a button on one frame, and that alone must not skip the claim."""
        empty = tuple(box for box in MAIL if box[0] != "Claim All")
        self.assertTrue(run_pass(self.task.show(empty)))
        self.assertEqual([], self.task.clicks)
        self.tick(daily.CLAIM_WAIT - 1)
        self.assertTrue(run_pass(self.task.show(MAIL)))
        self.assertPressed(daily.CLAIM_ALL)

    def test_items_obtained_closes_on_its_caption_never_the_enter_below(self):
        """3: Items Obtained after Claim All counts the mail as claimed."""
        self.state()["claim_pressed"] = START
        self.assertTrue(run_pass(self.task.show(ITEMS)))
        self.assertPressed(daily.ITEMS_CLOSE)
        self.assertNothingForbidden()
        self.assertEqual(daily.DONE, self.state()["steps"]["mail"])
        self.assertEqual("claimed", self.state()["mail"])

    def test_items_obtained_without_a_claim_all_is_closed_without_counting_the_mail(self):
        self.assertTrue(run_pass(self.task.show(ITEMS)))
        self.assertPressed(daily.ITEMS_CLOSE)
        self.assertEqual(daily.PENDING, self.state()["steps"]["mail"])

    def test_claim_all_is_read_through_ocr_mixing_up_capital_i_and_small_l(self):
        """274 and 276 read it `Claim AIl` and `Claim AlI` through the app's OCR settings."""
        for text in ("Claim All", "Claim AIl", "Claim AlI", "ClaimAll"):
            with self.subTest(text=text):
                screen = tuple((text, x, y) if name == "Claim All" else (name, x, y) for name, x, y in MAIL)
                self.assertEqual(text, daily.claim_all_button(self.task.show(screen)).name)
        for text in ("Claim", "Delete read mail", "Claim All Delete"):
            with self.subTest(text=text):
                screen = tuple((text, x, y) if name == "Claim All" else (name, x, y) for name, x, y in MAIL)
                self.assertIsNone(daily.claim_all_button(self.task.show(screen)))

    def test_claim_all_outside_its_band_is_not_claim_all(self):
        screen = tuple((name, 0.380, y) if name == "Claim All" else (name, x, y) for name, x, y in MAIL if name != "Delete read mail")
        self.assertIsNone(daily.claim_all_button(self.task.show(screen)))

    def test_a_greyed_claim_all_is_never_pressed_and_counts_as_no_mail_once_waited_on(self):
        """A live run pressed the greyed button twice. It is waited on as a missing one would be, since the popup may still be drawing."""
        self.task.show(MAIL_EMPTY, claim_all(lit=False))
        for _ in range(daily.CLAIM_WAIT):
            self.assertTrue(run_pass(self.task))
            self.tick()
        self.assertEqual([], self.task.clicks)
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.MAIL_CLOSE)
        self.assertEqual("nothing to claim", self.state()["mail"])
        self.assertIn("Claim All is greyed out, so there is no mail to claim", self.task.logged)
        self.assertNothingForbidden()

    def test_a_claim_all_turning_orange_inside_the_wait_is_pressed(self):
        self.task.show(MAIL, claim_all(lit=False))
        self.assertTrue(run_pass(self.task))
        self.tick(daily.CLAIM_WAIT - 1)
        self.assertTrue(run_pass(self.task.show(MAIL, claim_all(lit=True))))
        self.assertPressed(daily.CLAIM_ALL)

    def test_the_orange_claim_all_is_not_greyed_and_neither_is_a_frame_with_no_capture(self):
        self.assertTrue(daily.claim_all_greyed(self.task.show(MAIL_EMPTY, claim_all(lit=False))))
        self.assertFalse(daily.claim_all_greyed(self.task.show(MAIL, claim_all(lit=True))))
        self.assertFalse(daily.claim_all_greyed(self.task.show(MAIL)))

    def test_the_game_saying_every_mail_was_received_closes_the_popup_at_once(self):
        """The toast a press on the greyed button shows, read on the frame after a press made without a capture."""
        self.assertTrue(run_pass(self.task.show(MAIL)))
        self.tick()
        self.assertTrue(run_pass(self.task.show(MAIL_TOAST)))
        self.assertPressed(daily.CLAIM_ALL, daily.MAIL_CLOSE)
        self.assertEqual("nothing to claim", self.state()["mail"])

    def test_the_toast_read_off_its_place_is_not_taken_for_it(self):
        screen = MAIL_AFTER + (("All items in the mail have been received.", 0.500, 0.700),)
        self.assertTrue(run_pass(self.task.show(screen)))
        self.assertPressed(daily.CLAIM_ALL)

    def test_a_mail_count_or_title_missing_is_not_the_mail_screen(self):
        for missing in ("Mail", "003 / 100"):
            with self.subTest(missing=missing):
                self.assertFalse(daily.on_mail(self.task.show([box for box in MAIL if box[0] != missing])))


class TestAttendance(Daily):

    def run_screens(self, screens):
        for screen in screens:
            texts, frame = screen if isinstance(screen, tuple) and len(screen) == 2 and isinstance(screen[1], np.ndarray) else (screen, None)
            run_pass(self.task.show(texts, frame))
            self.tick()

    def test_todays_claim_reward_is_pressed_items_obtained_closed_then_the_popup_closed_on_its_x(self):
        """The stamped popup is left alone while the claim may still be landing, then closed on its X, with no stop."""
        self.run_screens([ATTENDANCE, ATTENDANCE_ITEMS] + [ATTENDANCE_STAMPED] * (daily.CLAIM_WAIT - 1))
        self.assertPressed(daily.ATTENDANCE_CLAIM, daily.ITEMS_CLOSE, daily.ATTENDANCE_CLOSE)
        self.assertNothingForbidden()
        self.assertEqual(0, self.task.disabled)

    def test_a_popup_already_claimed_is_given_time_to_draw_then_only_closed(self):
        """No Claim Reward: nothing on the first frame, then the X, and again only once the popup has had time to close."""
        self.task.show(ATTENDANCE_STAMPED)
        self.assertTrue(run_pass(self.task))
        self.assertEqual([], self.task.clicks)
        self.tick(daily.SETTLE)
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.ATTENDANCE_CLOSE)
        for _ in range(daily.NAV_WAIT - 1):
            self.tick()
            self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.ATTENDANCE_CLOSE)
        self.tick()
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.ATTENDANCE_CLOSE, daily.ATTENDANCE_CLOSE)
        self.assertEqual(0, self.task.disabled)

    def test_a_claim_that_opens_nothing_is_retried_once_then_the_popup_is_closed(self):
        self.task.show(ATTENDANCE)
        for _ in range(2 * daily.CLAIM_WAIT + 1):
            run_pass(self.task)
            self.tick()
        self.assertPressed(daily.ATTENDANCE_CLAIM, daily.ATTENDANCE_CLAIM, daily.ATTENDANCE_CLOSE)
        self.assertEqual(0, self.task.disabled)

    def test_the_popup_needs_its_title_and_its_tag_each_in_its_place(self):
        """Each also read where the Event list's page for the same event draws it, which is no popup."""
        moved = {"Invitation to a New Journey": (0.774, 0.136), "Permanent": (0.918, 0.201)}
        for text, place in moved.items():
            for case, screen in (("missing", tuple(box for box in ATTENDANCE if box[0] != text)),
                                 ("off its place", tuple((name, *place) if name == text else (name, x, y) for name, x, y in ATTENDANCE))):
                with self.subTest(text=text, case=case):
                    self.task = Task()
                    self.assertTrue(run_pass(self.task.show(screen)))
                    self.assertEqual([], self.task.clicks)

    def test_a_claim_reward_off_the_day_cards_is_not_pressed(self):
        """Over the art on the popup's left, where no card is, a Claim Reward is no claim; the popup is only closed."""
        off_cards = tuple(("Claim Reward", 0.200, 0.830) if box[0] == "Claim Reward" else box for box in ATTENDANCE)
        self.run_screens([off_cards] * (daily.SETTLE + 1))
        self.assertPressed(daily.ATTENDANCE_CLOSE)

    def test_the_event_lists_page_for_the_same_event_is_not_the_popup(self):
        """The list opened on the attendance event, today's card unclaimed: Dream Park is opened, no Claim Reward pressed."""
        self.to_park()
        unclaimed = tuple(("Claim Reward", x, y) if (name, x) == ("Awaiting Attendance", 0.543) else (name, x, y) for name, x, y in EVENT_LIST)
        self.assertTrue(run_pass(self.task.show(unclaimed)))
        self.assertPressed(daily.DREAM_PARK)

    def test_a_slow_items_obtained_on_the_mail_and_on_the_claim_each_get_their_own_presses(self):
        """Each Items Obtained shows for two frames: four caption presses in the run, two per screen, and no stop."""
        self.run_screens([LOBBY, MENU, MAIL, ITEMS, ITEMS, MAIL_AFTER, ATTENDANCE, ATTENDANCE_ITEMS, ATTENDANCE_ITEMS]
                         + [ATTENDANCE_STAMPED] * (daily.CLAIM_WAIT - 2))
        self.assertPressed(daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE, daily.ITEMS_CLOSE, daily.MAIL_CLOSE,
                           daily.ATTENDANCE_CLAIM, daily.ITEMS_CLOSE, daily.ITEMS_CLOSE, daily.ATTENDANCE_CLOSE)
        self.assertEqual(0, self.task.disabled)

    def test_the_claims_items_obtained_still_stops_at_its_own_limit(self):
        limit = daily.TAP_LIMITS[daily.ITEMS_CLOSE]
        self.run_screens([ATTENDANCE] + [ATTENDANCE_ITEMS] * (limit + 1))
        self.assertPressed(daily.ATTENDANCE_CLAIM, *[daily.ITEMS_CLOSE] * limit)
        self.assertStopped(f"{daily.ITEMS_CLOSE} was pressed {limit} times")

    def test_the_popup_restarts_the_unknown_screen_clock(self):
        run_pass(self.task.show(SETTINGS))
        self.tick(daily.UNKNOWN_SECONDS - 1)
        run_pass(self.task.show(ATTENDANCE_STAMPED))
        self.tick()
        run_pass(self.task.show(SETTINGS))
        self.assertEqual(0, self.task.disabled)

    def test_the_popup_after_the_mail_is_claimed_and_the_run_goes_on_to_the_park(self):
        """The live order: the Mail popup's X opens the attendance popup, and its X lands on the Lobby."""
        self.run_screens([LOBBY, MENU, MAIL, ITEMS, MAIL_AFTER, ATTENDANCE, ATTENDANCE_ITEMS] + [ATTENDANCE_STAMPED] * (daily.CLAIM_WAIT - 1)
                         + [LOBBY] + NOTHING_TO_CLAIM + NO_PARK_ROUTE + [LOBBY])
        self.assertPressed(daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE, daily.MAIL_CLOSE, daily.ATTENDANCE_CLAIM,
                           daily.ITEMS_CLOSE, daily.ATTENDANCE_CLOSE, daily.MENU, *NOTHING_TO_CLAIM_PRESSES, *NO_PARK_ROUTE_PRESSES)
        self.assertNothingForbidden()
        self.assertStopped("Daily finished: mail claimed; Dream Park is not running")


class TestLobbyAndMenu(Daily):

    def test_the_lobby_opens_the_menu_while_mail_is_pending_and_finishes_with_no_tap_once_done(self):
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.MENU)
        self.task.clicks.clear()
        self.state()["steps"]["mail"], self.state()["mail"] = daily.DONE, "claimed"
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.MENU)
        self.task.clicks.clear()
        self.finish_chores()
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Daily finished: mail claimed")

    def test_the_menu_opens_each_chore_while_pending_and_closes_once_done_never_shop_or_power(self):
        """5: on the plain menu and on the one with its key labels on, Activity and Achievement pressed on the boxes OCR read.

        The Carnival opens from the Lobby's banner, so with it next the menu is closed.
        """
        for screen in (MENU, MENU_KEYS):
            with self.subTest(keys=screen is MENU_KEYS):
                self.task = Task()
                self.assertTrue(run_pass(self.task.show(screen)))
                for step in BEFORE_PARK:
                    self.state()["steps"][step] = daily.DONE
                    self.assertTrue(run_pass(self.task))
                self.finish_chores()
                self.assertTrue(run_pass(self.task))
                self.assertPressed(daily.ENVELOPE, daily.ACTIVITY, daily.ACHIEVEMENT_ENTRY, daily.MENU_CLOSE, daily.EVENT, daily.MENU_CLOSE)
                self.assertNothingForbidden()

    def test_the_lobby_is_not_read_under_the_open_menu(self):
        self.assertFalse(daily.on_lobby(self.task.show(MENU)))
        self.assertFalse(daily.on_menu(self.task.show(LOBBY)))

    def test_every_screen_needs_both_of_its_captions(self):
        """One caption alone can be a fragment read through a popup, or another screen's word."""
        cases = ((daily.on_lobby, LOBBY, ("故事", "Combatants")), (daily.on_menu, MENU, ("Achievement", "Arkhianon Supply")),
                 (daily.on_notice, NOTICE, ("Notice", "Update")), (daily.on_mail, MAIL, ("Mail", "003 / 100")))
        for check, screen, captions in cases:
            self.assertTrue(check(self.task.show(screen)), captions)
            for caption in captions:
                with self.subTest(missing=caption):
                    self.assertFalse(check(self.task.show([box for box in screen if box[0] != caption])))
        for caption in ("Items Obtained", "点击屏幕关闭窗口"):
            with self.subTest(missing=caption):
                self.assertFalse(daily.handle_daily_items_obtained(self.task.show([box for box in ITEMS if box[0] != caption])))
        self.assertEqual([], self.task.clicks)

    def test_the_notice_board_is_closed_on_its_x_and_go_now_is_never_pressed(self):
        self.assertTrue(run_pass(self.task.show(NOTICE)))
        self.assertPressed(daily.NOTICE_CLOSE)
        self.assertNothingForbidden()


class TestBanner(Daily):

    def test_the_banner_x_is_found_on_the_banner_and_pressed(self):
        self.assertTrue(run_pass(self.task.show(BANNER, corner("daily_corner_banner"))))
        self.assertPressed(daily.BANNER_CLOSE)
        self.assertNothingForbidden()

    def test_the_lobby_the_menu_and_a_plain_x_are_not_the_banner(self):
        """7: the banner's X point lands on the Lobby's Menu, so a false match there opens the menu unasked."""
        for name in ("daily_corner_lobby", "daily_corner_menu", "daily_corner_plain_x"):
            with self.subTest(corner=name):
                frame = corner(name)
                self.assertIsNone(daily.find_icon(frame, daily.BANNER_CLOSE_IMAGE, daily.BANNER_MATCH, daily.BANNER_CORNER))
                self.assertFalse(daily.handle_daily_banner(self.task.show(BANNER, frame)))
        self.assertEqual([], self.task.clicks)

    def test_the_banner_x_outside_the_corner_is_not_the_banner(self):
        """7: a banner's X elsewhere would still get the tap at the corner's fixed point.

        Each X reaches 2 px past the corner's left or bottom edge, so a corner widened by 2 px takes in the whole X.
        """
        for where, region in (("across the left edge", (0.859375, 0.0, 0.959375, 0.12)), ("across the bottom edge", (0.90, 0.0454, 1.0, 0.1654))):
            with self.subTest(where=where):
                frame = placed("daily_corner_banner", region)
                self.assertIsNotNone(daily.find_icon(frame, daily.BANNER_CLOSE_IMAGE, daily.BANNER_MATCH, (0.0, 0.0, 1.0, 1.0)))
                self.assertFalse(daily.handle_daily_banner(self.task.show(BANNER, frame)))
        self.assertEqual([], self.task.clicks)

    def test_the_banner_check_stands_down_on_a_screen_another_check_knows(self):
        frame = corner("daily_corner_banner")
        for screen in (LOBBY, MENU, NOTICE):
            with self.subTest(screen=screen[0][0]):
                self.assertFalse(daily.handle_daily_banner(self.task.show(screen, frame)))
        self.assertEqual([], self.task.clicks)


class TestFadedLobby(Daily):

    def test_a_faded_lobby_moments_after_a_lobby_read_gets_the_menu_tap(self):
        run_pass(self.task.show(LOBBY))
        self.tick(19)
        self.assertTrue(run_pass(self.task.show(FADED, faded_lobby())))
        self.assertPressed(daily.MENU, daily.MENU)

    def test_a_faded_lobby_gets_no_menu_tap_without_a_recent_lobby_or_a_pending_step(self):
        """Past the Lobby read's time, or with every chore done, the faded Lobby gets the wake tap instead."""
        for case, wait in (("stale Lobby read", daily.FADED_SECONDS), ("chores done", 1)):
            with self.subTest(case=case):
                self.task = Task()
                run_pass(self.task.show(LOBBY))
                self.tick(wait)
                if wait == 1:
                    self.finish_chores()
                self.assertTrue(daily.handle_daily_faded_lobby(self.task.show(FADED, faded_lobby())))
                self.assertPressed(daily.MENU, daily.WAKE)

    def test_a_frame_reading_nothing_moments_after_a_lobby_read_gets_no_tap_unless_it_is_the_faded_lobby(self):
        """A live run pressed Menu on the Mail popup still loading and inside the park after a build, both read as nothing."""
        frames = {"black": np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8), "no capture": None}
        frames.update({name: placed(name, SCENE_REGION) for name in ("daily_blank_mail", "daily_blank_park", "daily_blank_cutscene")})
        for name, frame in frames.items():
            with self.subTest(frame=name):
                self.task = Task()
                run_pass(self.task.show(LOBBY))
                self.tick()
                self.assertFalse(daily.handle_daily_faded_lobby(self.task.show(FADED, frame)))
                self.assertPressed(daily.MENU)

    def test_a_line_of_text_without_the_faded_scene_is_not_a_faded_lobby(self):
        run_pass(self.task.show(LOBBY))
        self.assertFalse(daily.handle_daily_faded_lobby(self.task.show((("Loading", 0.5, 0.5),))))
        self.assertPressed(daily.MENU)

    def test_the_low_confidence_scrap_ocr_reads_off_the_faded_lobby_still_counts_as_faded(self):
        """264 read `rort` at 0.585 through the app's own OCR settings, whose floor is 0.2."""
        run_pass(self.task.show(LOBBY))
        self.task.show((("rort", 0.083, 0.531),), faded_lobby())
        self.task.all_texts[0].confidence = 0.585
        self.assertTrue(daily.handle_daily_faded_lobby(self.task))
        self.task.all_texts[0].confidence = 0.69
        self.assertTrue(daily.handle_daily_faded_lobby(self.task))
        self.task.all_texts[0].confidence = 0.7
        self.assertTrue(daily.reads_as_faded_lobby(self.task))
        self.task.show(FADED_BUBBLE + (("rort", 0.083, 0.531),), faded_lobby())
        self.task.all_texts[-1].confidence = 0.69
        self.assertTrue(daily.reads_as_faded_lobby(self.task))
        self.task.all_texts[-1].confidence = 0.7
        self.assertFalse(daily.handle_daily_faded_lobby(self.task))
        self.assertPressed(daily.MENU, daily.MENU, daily.MENU)


class TestFadedStart(Daily):
    """A start on an idle Lobby: no Lobby read yet, so only the faded Lobby's own scene earns the wake tap."""

    def test_a_start_on_a_faded_lobby_is_woken_once_then_runs_on(self):
        for _ in range(daily.WAKE_WAIT):
            self.assertTrue(run_pass(self.task.show(FADED, faded_lobby())))
            self.tick()
        self.assertPressed(daily.WAKE)
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.WAKE, daily.MENU)
        self.assertEqual(0, self.task.disabled)

    def test_the_faded_lobby_with_its_character_standing_is_woken_too(self):
        """352: the UI gone, the character still there."""
        self.assertTrue(run_pass(self.task.show(FADED, faded_lobby("daily_faded_lobby_character"))))
        self.assertPressed(daily.WAKE)

    def test_a_wake_the_game_ignored_is_retried_once_then_stops(self):
        self.task.show(FADED, faded_lobby())
        for _ in range(2 * daily.WAKE_WAIT):
            run_pass(self.task)
            self.tick()
        self.assertPressed(daily.WAKE, daily.WAKE)
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.WAKE, daily.WAKE)
        self.assertStopped("the faded Lobby's sky was pressed 2 times")

    def test_a_frame_that_reads_nothing_but_is_not_the_faded_lobby_gets_no_tap(self):
        """Black, a Rescue flash, a cut-scene and the carnival's intro read nothing too, as OCR saw them."""
        frames = {"black": np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8), "no capture": None}
        frames.update({name: placed(name, SCENE_REGION) for name in ("daily_blank_cutscene", "daily_blank_rescue_flash", "daily_blank_carnival")})
        for name, frame in frames.items():
            with self.subTest(frame=name):
                self.task = Task()
                for _ in range(daily.UNKNOWN_SECONDS):
                    self.assertTrue(run_pass(self.task.show(FADED, frame)))
                    self.tick()
                self.assertTrue(run_pass(self.task))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("Daily does not know this screen")

    def test_the_scene_half_covered_by_a_dialogue_is_not_the_faded_lobby(self):
        """326: the Lobby's scene under the tutorial's dialogue box came closest of every other capture, at 0.455."""
        frame = placed("daily_scene_under_dialogue", SCENE_REGION)
        self.assertIsNone(daily.find_icon(frame, daily.FADED_SCENE_IMAGE, daily.FADED_SCENE_MATCH, daily.FADED_SCENE_REGION, daily.grey))
        self.assertTrue(run_pass(self.task.show(FADED, frame)))
        self.assertEqual([], self.task.clicks)

    def test_the_faded_scene_under_a_popup_gets_no_wake(self):
        """A popup over the faded scene reads many lines, more than the one speech bubble a faded Lobby may show."""
        self.assertFalse(daily.handle_daily_faded_lobby(self.task.show(SETTINGS, faded_lobby())))
        self.assertEqual([], self.task.clicks)

    def test_a_lobby_faded_again_after_the_chores_is_woken_and_finishes(self):
        self.finish_chores()
        self.assertTrue(run_pass(self.task.show(FADED, faded_lobby())))
        self.tick()
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.WAKE)
        self.assertStopped("Daily finished: mail claimed")

    def test_the_menu_tap_moments_after_a_lobby_read_still_comes_first(self):
        run_pass(self.task.show(LOBBY))
        self.tick()
        self.assertTrue(run_pass(self.task.show(FADED, faded_lobby())))
        self.assertPressed(daily.MENU, daily.MENU)

    def test_the_wake_point_is_open_sky_away_from_every_target(self):
        """Measured on 264, 272, 352 and a live run's woken Lobby: no button within 0.08 of it on any of them."""
        for target, point in POINTS.items():
            if target != daily.WAKE:
                self.assertGreater(max(abs(point[0] - 0.300), abs(point[1] - 0.420)), 0.08, target)
        for screen in (LOBBY, MENU, TUTORIAL_LOBBY):
            self.assertEqual([], daily.boxes_at(self.task.show(screen), POINTS[daily.WAKE]))


class TestFadedBubble(Daily):
    """The faded Lobby with its character's speech bubble still reading, the one line it may show."""

    def test_a_start_on_a_faded_lobby_with_a_speech_bubble_is_woken_once_then_runs_on(self):
        for crop in ("daily_faded_lobby", "daily_faded_lobby_character"):
            with self.subTest(crop):
                self.task = Task()
                for _ in range(daily.WAKE_WAIT):
                    self.assertTrue(run_pass(self.task.show(FADED_BUBBLE, faded_lobby(crop))))
                    self.tick()
                self.assertPressed(daily.WAKE)
                self.assertTrue(run_pass(self.task.show(LOBBY)))
                self.assertPressed(daily.WAKE, daily.MENU)
                self.assertEqual(0, self.task.disabled)

    def test_a_faded_lobby_with_a_speech_bubble_moments_after_a_lobby_read_gets_the_menu_tap(self):
        run_pass(self.task.show(LOBBY))
        self.tick()
        self.assertTrue(run_pass(self.task.show(FADED_BUBBLE, faded_lobby())))
        self.assertPressed(daily.MENU, daily.MENU)

    def test_a_low_confidence_scrap_beside_the_bubble_still_counts_as_faded(self):
        self.task.show(FADED_BUBBLE + (("rort", 0.083, 0.531),), faded_lobby())
        self.task.all_texts[-1].confidence = 0.585
        self.assertTrue(daily.handle_daily_faded_lobby(self.task))
        self.assertPressed(daily.WAKE)

    def test_the_faded_scene_under_more_than_a_bubble_gets_no_wake(self):
        """A Lobby caption read at any confidence, a second confident line, or a line where the Lobby writes its captions."""
        story = FakeBox("故事", 0.884, 0.156)
        story.confidence = 0.5
        for label, texts, extra in (("a faint Story caption", FADED_BUBBLE, story),
                                    ("two lines", FADED_BUBBLE + (("Loading", 0.5, 0.5),), None),
                                    ("a line on the caption side", (("Combatants", daily.CAPTION_SIDE, 0.617),), None)):
            with self.subTest(label):
                self.task = Task()
                self.task.show(texts, faded_lobby())
                if extra is not None:
                    self.task.all_texts.append(extra)
                self.assertFalse(daily.handle_daily_faded_lobby(self.task))
                self.assertEqual([], self.task.clicks)

    def test_the_bubble_just_left_of_the_caption_side_still_counts_as_faded(self):
        self.task.show((("oh, I was writing a poem.", daily.CAPTION_SIDE - 0.01, 0.278),), faded_lobby())
        self.assertTrue(daily.handle_daily_faded_lobby(self.task))
        self.assertPressed(daily.WAKE)


class TestTutorial(Daily):
    """The tutorial's Skip Tutorial pill covers the Menu point, the banner's X and the menu's X, and a tap on it skips the tutorial."""

    def test_a_tutorial_lobby_stops_daily_with_nothing_pressed(self):
        self.assertTrue(run_pass(self.task.show(TUTORIAL_LOBBY)))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Skip Tutorial shows")

    def test_the_plain_lobby_still_gets_the_menu_tap(self):
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.MENU)
        self.assertEqual(0, self.task.disabled)

    def test_the_pill_stops_daily_on_every_screen_it_presses_on(self):
        for name, texts, frame in (("menu", MENU, None), ("notice", NOTICE, None), ("mail", MAIL, None), ("items", ITEMS, None),
                                   ("banner", BANNER, corner("daily_corner_banner")), ("unknown", SETTINGS, None)):
            with self.subTest(screen=name):
                self.task = Task()
                self.assertTrue(run_pass(self.task.show(texts + (SKIP_TUTORIAL,), frame)))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("Skip Tutorial shows")

    def test_the_pill_is_read_anywhere_and_with_its_space_dropped(self):
        """Its text centre has sat at x 0.879-0.880, but a tap on the Menu point lands on the pill wherever its caption reads."""
        for name, box in (("left of its place", ("Skip Tutorial", 0.70, 0.06)), ("lower", ("Skip Tutorial", 0.88, 0.15)),
                          ("space dropped", ("SkipTutorial", 0.879, 0.055)), ("upper case", ("SKIP TUTORIAL", 0.879, 0.055))):
            with self.subTest(pill=name):
                self.task = Task()
                self.assertTrue(run_pass(self.task.show(LOBBY + (box,))))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("Skip Tutorial shows")

    def test_a_pill_read_at_low_confidence_after_a_lobby_read_gets_no_faded_tap(self):
        """A frame reading only the pill, faintly, would otherwise count as a faded Lobby and get the Menu tap on the pill."""
        run_pass(self.task.show(LOBBY))
        self.tick()
        self.task.show((SKIP_TUTORIAL,))
        self.task.all_texts[0].confidence = 0.5
        self.assertTrue(run_pass(self.task))
        self.assertPressed(daily.MENU)
        self.assertStopped("Skip Tutorial shows")

    def test_the_pill_mid_run_stops_daily_before_its_next_press(self):
        screens = [LOBBY, MENU, MAIL + (SKIP_TUTORIAL,), ITEMS]
        for texts in screens:
            if not self.task.enabled:
                break
            run_pass(self.task.show(texts))
            self.tick()
        self.assertPressed(daily.MENU, daily.ENVELOPE)
        self.assertStopped("Skip Tutorial shows")

    def test_the_targets_it_covers_are_the_ones_measured(self):
        """The Menu, the banner's X and the menu's X lie on the pill; Daily's other fixed points do not.

        The Mail popup's X lies 0.002 below the outline but inside the box the guard in `skip_tutorial` refuses.
        """
        left, top, right, bottom = SKIP_TUTORIAL_PILL
        covered = {name for name, point in POINTS.items() if left <= point[0] <= right and top <= point[1] <= bottom}
        self.assertEqual({daily.MENU, daily.BANNER_CLOSE, daily.MENU_CLOSE}, covered)
        self.assertEqual(SKIP_TUTORIAL_PILL, skip_tutorial.OUTLINE)
        left, top, right, bottom = skip_tutorial.GUARDED
        guarded = {name for name, point in POINTS.items() if left <= point[0] <= right and top <= point[1] <= bottom}
        self.assertEqual(covered | {daily.MAIL_CLOSE}, guarded)

    def test_the_pill_on_the_mail_popup_stops_daily_before_its_x(self):
        self.state()["steps"]["mail"] = daily.DONE
        self.assertTrue(run_pass(self.task.show(MAIL_AFTER + (SKIP_TUTORIAL,))))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Skip Tutorial shows")


class TestStops(Daily):

    UNKNOWN_STOP = "Stopped: Daily does not know this screen and pressed nothing for 30s. Go back to the Lobby, then press Start again."

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(daily, "logger")
        patcher.start()
        self.addCleanup(patcher.stop)

    def unknown_frame(self):
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        frame[100:200, 300:500] = (10, 200, 30)
        return frame

    def stay_unknown(self, frame):
        """Show a screen Daily does not know for `UNKNOWN_SECONDS`, one pass a second, then once more."""
        for elapsed in range(daily.UNKNOWN_SECONDS):
            self.assertTrue(run_pass(self.task.show(SETTINGS, frame)), elapsed)
            self.tick()
        self.assertTrue(run_pass(self.task))

    def test_an_unknown_screen_gets_no_press_and_stops_after_thirty_seconds(self):
        for elapsed in range(30):
            self.assertTrue(run_pass(self.task.show(SETTINGS)), elapsed)
            self.assertEqual(0, self.task.disabled, elapsed)
            self.tick()
        self.assertTrue(run_pass(self.task))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Daily does not know this screen")

    def test_a_known_screen_restarts_the_unknown_clock(self):
        run_pass(self.task.show(SETTINGS))
        self.tick(29)
        run_pass(self.task.show(NOTICE))
        self.tick()
        run_pass(self.task.show(SETTINGS))
        self.assertEqual(0, self.task.disabled)

    def test_the_unknown_stop_saves_its_frame_once_before_it_stops(self):
        folder, frame = self.unknown_folder, self.unknown_frame()
        for elapsed in range(daily.UNKNOWN_SECONDS):
            run_pass(self.task.show(SETTINGS, frame))
            self.assertFalse(folder.exists(), elapsed)
            self.tick()
        self.assertTrue(run_pass(self.task))
        saved = list(folder.iterdir())
        self.assertEqual(1, len(saved), saved)
        self.assertRegex(saved[0].name, r"^\d{4}-\d{2}-\d{2}_\d{6}\.png$")
        self.assertTrue(np.array_equal(frame, cv2.imdecode(np.fromfile(saved[0], np.uint8), cv2.IMREAD_COLOR)))
        self.assertEqual([], self.task.clicks)
        self.assertStopped(self.UNKNOWN_STOP)
        self.assertEqual([self.UNKNOWN_STOP], self.task.notifications)
        self.assertIn(str(saved[0]), daily.logger.info.call_args.args[0])
        daily.logger.warning.assert_not_called()

    def test_a_failed_save_still_stops_with_the_same_message_and_leaves_no_file(self):
        def partial_write(path, data):
            with open(path, "wb") as file:
                file.write(data[:8])
            raise OSError("disk full")

        failures = {
            "encoder": mock.patch.object(daily.cv2, "imencode", return_value=(False, None)),
            "folder": mock.patch.object(Path, "mkdir", side_effect=OSError("access denied")),
            "write": mock.patch.object(Path, "write_bytes", partial_write),
        }
        for name, failure in failures.items():
            with self.subTest(failure=name):
                self.task = Task()
                daily.logger.reset_mock()
                folder = self.unknown_folder
                with failure:
                    self.stay_unknown(self.unknown_frame())
                self.assertEqual([], list(folder.iterdir()) if folder.exists() else [])
                self.assertEqual([], self.task.clicks)
                self.assertStopped(self.UNKNOWN_STOP)
                self.assertEqual([self.UNKNOWN_STOP], self.task.notifications)
                self.assertEqual(1, daily.logger.warning.call_count)

    def test_an_unknown_stop_without_a_frame_still_stops_and_saves_nothing(self):
        folder = self.unknown_folder
        self.stay_unknown(None)
        self.assertFalse(folder.exists())
        self.assertStopped(self.UNKNOWN_STOP)
        self.assertEqual(1, daily.logger.warning.call_count)

    def test_a_rescue_screen_or_dialog_stops_at_once_with_nothing_pressed(self):
        for screen in (RESCUE, PAID_RESCUE):
            with self.subTest(screen=screen[0][0]):
                self.task = Task()
                self.assertTrue(run_pass(self.task.show(screen)))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("Rescue screen")

    def test_a_run_past_its_time_limit_stops_with_nothing_pressed(self):
        self.state()
        self.tick(daily.RUN_SECONDS)
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Daily ran for 10 minutes")

    def test_every_target_stops_at_its_limit(self):
        for target, limit in daily.TAP_LIMITS.items():
            with self.subTest(target=target):
                self.task = Task()
                box = FakeBox(target, *POINTS[target]) if daily.TARGETS[target] is None else None
                for _ in range(limit + 1):
                    daily.press(self.task, target, box)
                self.assertEqual(limit, len(self.task.clicks))
                self.assertStopped(f"{target} was pressed {limit} times")

    def test_only_a_rides_upgrade_watches_its_level_instead_of_the_full_wait(self):
        for target in daily.TAP_LIMITS:
            with self.subTest(target=target):
                self.task = Task()
                box = FakeBox(target, *POINTS[target]) if daily.TARGETS[target] is None else None
                daily.press(self.task, target, box, 7)
                upgrade = target == daily.UPGRADE
                self.assertEqual([0 if upgrade else story.AFTER_TAP], self.task.waits)
                self.assertEqual(upgrade, bool(self.task.zones))

    def test_the_limits_are_as_designed(self):
        special = {daily.CLAIM_ALL: 2, daily.ATTENDANCE_CLAIM: 2, daily.WAKE: 2, daily.RANK_UP: 2, daily.UPGRADE: 200, daily.CLAIM: 30, daily.SKIP_TICK: 1,
                   daily.SKILL_UPGRADE: 30, daily.HAPPY_DAY_UPGRADE: 30, daily.GUIDE_CLAIM: 15, daily.SCHEDULE_CLAIM: 2, daily.GOAL_CLAIM: 6,
                   daily.MILESTONE_CLAIM: 2, daily.LOG_CLAIM: 2, daily.CATEGORY_CLAIM: 2, daily.CARNIVAL_TAB: 2, daily.CARNIVAL_DAY: 2,
                   daily.CAPTAIN_CLAIM: 6, daily.PROMOTE: 2, daily.LEVEL_UP: 6, daily.AUTO_REGISTER: 8, daily.ACTIVATE: 10}
        self.assertEqual({target: special.get(target, 3) for target in POINTS}, daily.TAP_LIMITS)
        self.assertEqual(set(POINTS), set(daily.TARGETS))

    def test_menu_and_mail_presses_count_only_until_the_mail_screen_shows(self):
        """A later step opens the menu again, and the presses that got the mail open were not stuck ones."""
        for _ in range(daily.TAP_LIMITS[daily.MENU]):
            daily.press(self.task, daily.MENU)
        run_pass(self.task.show(MAIL))
        self.assertTrue(daily.press(self.task, daily.MENU))
        self.assertEqual(0, self.task.disabled)


class TestRefusals(Daily):

    def test_a_target_over_a_box_that_must_never_be_pressed_stops_instead(self):
        """The backstop under every press: each marker under the Menu point, on the Lobby."""
        for text in ("Delete read mail", "Delete", "Shop", "Purchase", "Buy", "Spend 1600 Crystals", "US$4.99", "₩1,200", "营救", "Aether"):
            with self.subTest(text=text):
                self.task = Task()
                self.task.show(LOBBY + ((text, *POINTS[daily.MENU]),))
                self.assertTrue(run_pass(self.task))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("would have pressed")

    def test_card_text_holding_the_currency_name_is_not_refused(self):
        """The backstop reads the spend guard's markers, so a card word is no Crystal there either."""
        for text in ("2 Crystallization", "Foggy Crystal Ball"):
            with self.subTest(text=text):
                self.assertIsNone(daily.refused(text))
        for text in ("30 Crystals", "Crystalx100", "6.37K Crystal"):
            with self.subTest(text=text):
                self.assertEqual("crystal", daily.refused(text))

    def test_a_rescue_phrase_is_refused_by_the_backstop_too(self):
        """On a whole screen the Rescue stop sees it first, so the backstop is checked on its own."""
        for text in ("Rescue 10 time(s)", "Selective Rescue", "Free Rescue", "Rescue"):
            with self.subTest(text=text):
                self.assertIsNotNone(daily.refused(text))
                self.task = Task()
                self.task.show(((text, *POINTS[daily.MENU]),))
                self.assertTrue(daily.press(self.task, daily.MENU))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("would have pressed")

    def test_a_retreat_word_under_a_press_stops_instead(self):
        """The Escape that abandons an open run, and every other retreat word the spend guard knows, under the Menu point."""
        for text in ("Escape", "Retreat", "逃脱", "脱逃", "Abandon", "Give Up"):
            with self.subTest(text=text):
                self.task = Task()
                self.task.show(LOBBY + ((text, *POINTS[daily.MENU]),))
                self.assertTrue(run_pass(self.task))
                self.assertEqual([], self.task.clicks)
                self.assertStopped("would have pressed")

    def test_a_press_landing_on_a_run_s_escape_stops_daily(self):
        """The Escape box pressed, or another box read over it, on the resume prompt and on Chaos Info."""
        # Imported here: that module imports this one through TestChaosEntry.
        from tests.TestSpendGuard import CHAOS_INFO, RESUME
        for screen, texts in (("resume prompt", RESUME), ("Chaos Info", CHAOS_INFO)):
            escape = next(box for box in texts if box[0] == "Escape")
            for label, box in (("the Escape box", escape), ("an Enter read over it", ("进入", *escape[1:]))):
                with self.subTest(screen=screen, pressed=label):
                    self.task = Task()
                    self.task.show(texts)
                    self.assertTrue(daily.press(self.task, daily.RANK_UP, FakeBox(*box)))
                    self.assertEqual([], self.task.clicks)
                    self.assertStopped("would have pressed 'Escape'")

    def test_a_press_beside_a_run_s_escape_is_still_made(self):
        """The Rank button's point on Chaos Info lies just below its End and well left of its Escape."""
        from tests.TestSpendGuard import CHAOS_INFO
        self.assertTrue(daily.press(self.task.show(CHAOS_INFO), daily.PARK_RANK))
        self.assertPressed(daily.PARK_RANK)
        self.assertEqual(0, self.task.disabled)

    def test_a_text_button_reading_as_a_refused_word_is_not_pressed(self):
        self.assertTrue(daily.press(self.task, daily.CLAIM_ALL, FakeBox("Delete read mail", *NEVER["Delete read mail"])))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("would have pressed")

    def test_the_backstop_passes_every_target_on_its_own_screen(self):
        """Nothing Daily presses reads as a refused word, the menu's Shop and Rescue lying well away from its targets."""
        for screen in (LOBBY, MENU, MENU_KEYS, NOTICE, MAIL, MAIL_AFTER, ITEMS, ATTENDANCE, ATTENDANCE_STAMPED):
            for box in screen:
                if box[0] in ("Shop", "营救", "Delete read mail", "Delete"):
                    self.assertIsNotNone(daily.refused(box[0]), box[0])
        for target, point in POINTS.items():
            for screen in (LOBBY, MENU, NOTICE, MAIL, MAIL_AFTER, ITEMS, ATTENDANCE, ATTENDANCE_STAMPED):
                hits = daily.boxes_at(self.task.show(screen), point)
                self.assertEqual([], [box.name for box in hits if daily.refused(box.name)], target)

    def test_negative_control_a_loose_claim_all_without_the_backstop_presses_delete(self):
        """12: proves test 1's check bites. With the backstop gone and Claim All matched as the bottom bar's second button, Delete is pressed."""
        with mock.patch.object(daily, "claim_all_button", second_bottom_button), mock.patch.object(daily, "refused", lambda text: None):
            run_pass(self.task.show(MAIL_AFTER))
        with self.assertRaises(AssertionError):
            self.assertNothingForbidden()

    def test_a_loose_claim_all_alone_is_stopped_by_the_backstop(self):
        with mock.patch.object(daily, "claim_all_button", second_bottom_button):
            run_pass(self.task.show(MAIL_AFTER))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("would have pressed 'Delete read mail'")


class TestWholeRun(Daily):

    # The park step after the mail, on a client whose Event list no longer has Dream Park.
    NO_PARK = NOTHING_TO_CLAIM + NO_PARK_ROUTE
    NO_PARK_PRESSES = (daily.MENU, *NOTHING_TO_CLAIM_PRESSES, *NO_PARK_ROUTE_PRESSES)

    def run_screens(self, screens):
        for screen in screens:
            texts, frame = screen if isinstance(screen, tuple) and len(screen) == 2 and isinstance(screen[1], np.ndarray) else (screen, None)
            run_pass(self.task.show(texts, frame))
            self.tick()

    def test_banner_notice_menu_mail_claim_and_the_x_back_to_a_finished_lobby(self):
        """The order the live client showed, the Mail popup's X landing on the Lobby with the menu closed."""
        self.run_screens([(BANNER, corner("daily_corner_banner")), NOTICE, LOBBY, MENU, (MAIL, claim_all(lit=True)), ITEMS,
                          (MAIL_AFTER, claim_all(lit=False)), LOBBY] + self.NO_PARK + [LOBBY])
        self.assertPressed(daily.BANNER_CLOSE, daily.NOTICE_CLOSE, daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE,
                           daily.MAIL_CLOSE, *self.NO_PARK_PRESSES)
        self.assertNothingForbidden()
        self.assertStopped("Daily finished: mail claimed; Dream Park is not running")

    def test_an_x_landing_on_the_open_menu_goes_on_to_the_event_list_and_finishes(self):
        self.run_screens([LOBBY, MENU, MAIL, ITEMS, MAIL_AFTER] + self.NO_PARK + [LOBBY])
        self.assertPressed(daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE, daily.MAIL_CLOSE, *self.NO_PARK_PRESSES[1:])
        self.assertStopped("Daily finished: mail claimed")

    def test_an_empty_mailbox_presses_no_claim_all_and_ends_on_the_lobby(self):
        """The live run's order: the popup with Claim All greyed, then the Lobby the X lands on."""
        empty = (MAIL_EMPTY, claim_all(lit=False))
        self.run_screens([LOBBY, MENU] + [empty] * (daily.CLAIM_WAIT + 1) + [LOBBY] + self.NO_PARK + [LOBBY])
        self.assertPressed(daily.MENU, daily.ENVELOPE, daily.MAIL_CLOSE, *self.NO_PARK_PRESSES)
        self.assertNothingForbidden()
        self.assertStopped("Daily finished: no mail to claim")

    def test_a_start_on_a_faded_lobby_wakes_it_claims_and_ends_on_the_lobby(self):
        self.run_screens([(FADED, faded_lobby()), LOBBY, MENU, (MAIL, claim_all(lit=True)), ITEMS, (MAIL_AFTER, claim_all(lit=False)), LOBBY]
                         + self.NO_PARK + [LOBBY])
        self.assertPressed(daily.WAKE, daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE, daily.MAIL_CLOSE, *self.NO_PARK_PRESSES)
        self.assertNothingForbidden()
        self.assertStopped("Daily finished: mail claimed")


# The ready patches, each over the screen it was cut from.
GUIDE_STAGE_READY = (GUIDE_DONE, placed("activity_stage_ring_ready", STAGE_CROP))
GUIDE_STAGE_GREYED = (GUIDE_DONE, placed("activity_stage_ring_greyed", STAGE_CROP))
SCHEDULE_READY = (SCHEDULE, placed("activity_schedule_lit", SCHEDULE_CROP))
WEEKLY_GOAL_READY = (WEEKLY_GOAL, composed(("activity_goal_lit", GOAL_CROP), ("activity_milestones_claimed", MILESTONES_CROP)))
WEEKLY_GOAL_TAKEN = (WEEKLY_AFTER, composed(("activity_goal_gone", GOAL_CROP), ("activity_milestones_claimed", MILESTONES_CROP)))
WEEKLY_MILESTONES_READY = (WEEKLY_MILESTONES, composed(("activity_goal_gone", GOAL_CROP), ("activity_milestones_lit", MILESTONES_CROP)))
LOG_READY = (LOG, placed("activity_log_rows", LOG_CROP))
CATEGORY_READY = (CATEGORY_JOURNEY, placed("achievement_claim_all_lit", CATEGORY_CROP))


class Claims(Daily):
    """Daily on the Activity window and the Achievement screen."""

    def run_screens(self, screens):
        for screen in screens:
            texts, frame = screen if isinstance(screen, tuple) and len(screen) == 2 and isinstance(screen[1], np.ndarray) else (screen, None)
            run_pass(self.task.show(texts, frame))
            self.tick()

    def on_step(self, name):
        """Count the chores before the named one as done, the mail claimed."""
        steps = self.state()["steps"]
        for step in BEFORE_PARK[:BEFORE_PARK.index(name)]:
            steps[step] = daily.DONE
        self.state()["mail"] = "claimed"

    def ready(self, screen, tab):
        """Give what `ready_activity_claim` finds on a `(texts, frame)` screen."""
        texts, frame = screen if isinstance(screen[1], np.ndarray) else (screen, None)
        return daily.ready_activity_claim(self.task.show(texts, frame), tab)

    def assertClaim(self, found, target, point=None):
        """Check a claim was found for the target, at the point when given."""
        self.assertIsNotNone(found)
        self.assertEqual(target, found[0])
        if point is not None:
            x, y = daily.centre_of(found[2], WIDTH, HEIGHT) if found[2] is not None else daily.TARGETS[target]
            self.assertAlmostEqual(point[0], x, delta=0.005)
            self.assertAlmostEqual(point[1], y, delta=0.005)


class TestActivityReaders(Claims):

    def test_the_first_ready_growth_guide_card_is_found_never_the_one_cut_at_the_edge(self):
        self.assertClaim(self.ready(GUIDE_READY, daily.GUIDE), daily.GUIDE_CLAIM, POINTS[daily.GUIDE_CLAIM])
        self.assertIsNone(self.ready((("Growth Guide", 0.171, 0.112), ("Claim Reward", 0.934, 0.853)), daily.GUIDE))

    def test_a_growth_guide_with_every_card_on_move_has_nothing_ready(self):
        self.assertIsNone(self.ready(GUIDE_NOTHING, daily.GUIDE))

    def test_the_stage_ring_is_ready_only_while_orange(self):
        """1126 against 1128's ring, both under 1126's text, where every card is claimed."""
        self.assertClaim(self.ready(GUIDE_STAGE_READY, daily.GUIDE), daily.STAGE_CLAIM, POINTS[daily.STAGE_CLAIM])
        self.assertIsNone(self.ready(GUIDE_STAGE_GREYED, daily.GUIDE))
        self.assertIsNone(self.ready(GUIDE_DONE, daily.GUIDE))

    def test_the_daily_claim_all_is_ready_only_while_orange_and_read(self):
        """1200 against 1202; OCR read 1200's caption as `Claim AIl`."""
        self.assertClaim(self.ready(SCHEDULE_READY, daily.SCHEDULE), daily.SCHEDULE_CLAIM, POINTS[daily.SCHEDULE_CLAIM])
        self.assertIsNone(self.ready(SCHEDULE_NOTHING, daily.SCHEDULE))
        self.assertIsNone(self.ready((SCHEDULE, SCHEDULE_NOTHING[1]), daily.SCHEDULE))
        self.assertIsNone(self.ready((tuple(box for box in SCHEDULE if box[0] != "Claim AIl"), SCHEDULE_READY[1]), daily.SCHEDULE))

    def test_claim_all_is_read_however_ocr_spelled_it(self):
        for text in ("Claim All", "Claim AIl", "Claim AlI", "Claim AIll"):
            with self.subTest(text=text):
                self.assertIsNotNone(daily.claim_all_in(self.task.show(((text, 0.226, 0.838),)), daily.SCHEDULE_BUTTON_REGION))
        for text in ("Claim", "Claim Reward", "All"):
            with self.subTest(text=text):
                self.assertIsNone(daily.claim_all_in(self.task.show(((text, 0.226, 0.838),)), daily.SCHEDULE_BUTTON_REGION))

    def test_a_goal_is_ready_only_with_its_caption_on_an_orange_face(self):
        """1317 against 1319, where the card has left the row and a grey Move took its place."""
        self.assertClaim(self.ready(WEEKLY_GOAL_READY, daily.WEEKLY), daily.GOAL_CLAIM, POINTS[daily.GOAL_CLAIM])
        self.assertIsNone(self.ready(WEEKLY_GOAL_TAKEN, daily.WEEKLY))
        self.assertIsNone(self.ready((WEEKLY_GOAL, WEEKLY_GOAL_TAKEN[1]), daily.WEEKLY))

    def test_a_reached_milestone_is_ready_only_while_its_label_is_orange(self):
        """709 against 711, after one press took both reached tiers."""
        self.assertClaim(self.ready(WEEKLY_MILESTONES_READY, daily.WEEKLY), daily.MILESTONE_CLAIM, POINTS[daily.MILESTONE_CLAIM])
        self.assertIsNone(self.ready(WEEKLY_NOTHING, daily.WEEKLY))

    def test_the_log_claim_is_ready_only_while_the_top_row_is_orange(self):
        """790's top row and 1424's against 790's second row moved up into its place, and 714 after the claim."""
        self.assertClaim(self.ready(LOG_READY, daily.LOG), daily.LOG_CLAIM, POINTS[daily.LOG_CLAIM])
        self.assertClaim(self.ready((LOG_LV19, placed("activity_log_ready_top", LOG_CROP)), daily.LOG), daily.LOG_CLAIM)
        second_row = (LOG_CROP[0], LOG_CROP[1] - LOG_ROW, LOG_CROP[2], LOG_CROP[3] - LOG_ROW)
        self.assertIsNone(self.ready((LOG, placed("activity_log_rows", second_row)), daily.LOG))
        self.assertIsNone(self.ready(LOG_NOTHING, daily.LOG))

    def test_the_window_is_told_by_its_tab_title_and_nothing_else_is(self):
        tabs = {daily.GUIDE: (GUIDE_READY, GUIDE_MOVE, GUIDE_DONE, GUIDE_NEXT_STAGE), daily.SCHEDULE: (SCHEDULE, SCHEDULE_AFTER),
                daily.WEEKLY: (WEEKLY_GOAL, WEEKLY_AFTER, WEEKLY_MILESTONES, WEEKLY_CLAIMED), daily.LOG: (LOG, LOG_AFTER, LOG_LV19)}
        for tab, screens in tabs.items():
            for screen in screens:
                self.assertEqual(tab, daily.activity_tab(self.task.show(screen)))
        for screen in (LOBBY, MENU, MAIL, ITEMS, CLAIM_ITEMS, ACHIEVEMENT_CARDS, CATEGORY_JOURNEY, CATEGORY_OVERCOMING_DONE, EVENT_LIST):
            self.assertIsNone(daily.activity_tab(self.task.show(screen)))

    def test_the_achievement_screens_are_told_apart(self):
        self.assertEqual(0, daily.category_shown(self.task.show(CATEGORY_JOURNEY)))
        self.assertEqual(1, daily.category_shown(self.task.show(CATEGORY_EXPLORATION_DONE)))
        self.assertEqual(1, daily.category_shown(self.task.show(edited_text(CATEGORY_EXPLORATION_DONE, "Exploration Attitude", "Exploratin Atitude"))))
        self.assertEqual(2, daily.category_shown(self.task.show(CATEGORY_TRACES_DONE)))
        self.assertEqual(3, daily.category_shown(self.task.show(CATEGORY_OVERCOMING_DONE)))
        self.assertEqual(-1, daily.category_shown(self.task.show(edited_text(CATEGORY_JOURNEY, "Journey Log", "", at=0.376))))
        for screen in (ACHIEVEMENT_CARDS, GUIDE_READY, LOG, MENU, LOBBY):
            self.assertIsNone(daily.category_shown(self.task.show(screen)))
        self.assertTrue(daily.handle_daily_achievement_cards(self.task.show(ACHIEVEMENT_CARDS)))
        self.assertFalse(daily.handle_daily_achievement_cards(self.task.show(CATEGORY_JOURNEY)))

    def test_claim_captions_are_never_refused_and_the_shop_is(self):
        for text in ("Claim Reward", "Claim All", "Claim AIl", "Goal Achieved", "Activity", "Achievement", "Journey Log", "Complete", "Move"):
            with self.subTest(text=text):
                self.assertIsNone(daily.refused(text))
        self.assertIsNotNone(daily.refused("Mission Records Shop"))

    def test_the_backstop_passes_every_new_target_on_its_screens(self):
        """The Lv 22 label misread as `$22$` on 1424 reads as a price, but lies far from the log's claim."""
        self.assertIsNotNone(daily.refused("$22$"))
        screens = {
            (daily.GUIDE_TAB, daily.SCHEDULE_TAB, daily.WEEKLY_TAB, daily.LOG_TAB, daily.ACTIVITY_CLOSE, daily.GUIDE_CLAIM, daily.STAGE_CLAIM):
                (GUIDE_READY, GUIDE_MOVE, GUIDE_DONE, GUIDE_NEXT_STAGE),
            (daily.GUIDE_TAB, daily.WEEKLY_TAB, daily.LOG_TAB, daily.ACTIVITY_CLOSE, daily.SCHEDULE_CLAIM): (SCHEDULE, SCHEDULE_AFTER),
            (daily.GUIDE_TAB, daily.SCHEDULE_TAB, daily.LOG_TAB, daily.ACTIVITY_CLOSE, daily.GOAL_CLAIM, daily.MILESTONE_CLAIM):
                (WEEKLY_GOAL, WEEKLY_AFTER, WEEKLY_MILESTONES, WEEKLY_CLAIMED),
            (daily.GUIDE_TAB, daily.SCHEDULE_TAB, daily.WEEKLY_TAB, daily.ACTIVITY_CLOSE, daily.LOG_CLAIM): (LOG, LOG_AFTER, LOG_LV19),
            (daily.JOURNEY_CARD, daily.CARDS_LEAVE): (ACHIEVEMENT_CARDS,),
            (*daily.CATEGORY_TABS, daily.CATEGORY_CLAIM, daily.CATEGORY_LEAVE): (CATEGORY_JOURNEY, CATEGORY_JOURNEY_DONE, CATEGORY_OVERCOMING_DONE),
        }
        for targets, texts in screens.items():
            for screen in texts:
                for target in targets:
                    hits = daily.boxes_at(self.task.show(screen), POINTS[target])
                    self.assertEqual([], [box.name for box in hits if daily.refused(box.name) or daily.folded(box.name) in daily.NEVER_CLAIM], target)


def edited_text(screen, old, new, at=None):
    """Give a screen with one box's text changed, the first reading `old`, or the one at x `at` when given."""
    done = False
    edited = []
    for name, x, y in screen:
        if not done and name == old and (at is None or x == at):
            edited.append((new, x, y))
            done = True
        else:
            edited.append((name, x, y))
    return tuple(edited)


class TestActivity(Claims):

    def setUp(self):
        super().setUp()
        self.on_step("activity")

    def test_every_tab_is_claimed_in_turn_then_the_window_is_closed(self):
        """Six claims in one run, each closing its own Items Obtained, a weekly goal counted by its card leaving, and one
        milestone press counted as both tiers it took."""
        self.run_screens([GUIDE_READY] * SETTLED + [CLAIM_ITEMS] + [GUIDE_STAGE_READY] * SETTLED + [CLAIM_ITEMS] + [GUIDE_NOTHING] * SETTLED
                         + [SCHEDULE_READY] * SETTLED + [CLAIM_ITEMS] + [SCHEDULE_NOTHING] * SETTLED
                         + [WEEKLY_GOAL_READY] * SETTLED + [(WEEKLY_AFTER, WEEKLY_MILESTONES_READY[1])] * daily.CLAIM_WAIT + [CLAIM_ITEMS]
                         + [WEEKLY_NOTHING] * SETTLED + [LOG_READY] * SETTLED + [CLAIM_ITEMS] + [LOG_NOTHING] * SETTLED)
        self.assertPressed(daily.GUIDE_CLAIM, daily.ITEMS_CLOSE, daily.STAGE_CLAIM, daily.ITEMS_CLOSE, daily.SCHEDULE_TAB, daily.SCHEDULE_CLAIM,
                           daily.ITEMS_CLOSE, daily.WEEKLY_TAB, daily.GOAL_CLAIM, daily.MILESTONE_CLAIM, daily.ITEMS_CLOSE, daily.LOG_TAB,
                           daily.LOG_CLAIM, daily.ITEMS_CLOSE, daily.ACTIVITY_CLOSE)
        self.assertNothingForbidden()
        self.assertEqual(0, self.task.disabled)
        self.assertEqual(daily.DONE, self.state()["steps"]["activity"])
        self.assertEqual({"guide": 1, "stage": 1, "schedule": 1, "goal": 1, "milestone": 2, "log": 1}, dict(self.state()["claims"]["claimed"]))

    def test_four_claims_in_a_row_each_close_their_items_obtained(self):
        """The caption's run limit of 3 counts afresh on the Activity window, so a fourth claim is not cut short."""
        self.run_screens(([GUIDE_READY] * SETTLED + [CLAIM_ITEMS]) * 4)
        self.assertPressed(*(daily.GUIDE_CLAIM, daily.ITEMS_CLOSE) * 4)
        self.assertEqual(0, self.task.disabled)
        self.assertEqual(4, self.state()["claims"]["claimed"]["guide"])

    def test_negative_control_without_the_items_reset_the_fourth_claim_stops(self):
        """Proves the test above bites: with the caption's count kept across the window, its fourth Items Obtained stops Daily."""
        original = daily.arrive_claim_screen

        def keeping_the_caption_count(task, screen, entries):
            taps = daily.run_state(task)["taps"]
            kept = taps[daily.ITEMS_CLOSE]
            shown_for = original(task, screen, entries)
            taps[daily.ITEMS_CLOSE] = kept
            return shown_for

        with mock.patch.object(daily, "arrive_claim_screen", keeping_the_caption_count):
            self.run_screens(([GUIDE_READY] * SETTLED + [CLAIM_ITEMS]) * 4)
        self.assertStopped(f"{daily.ITEMS_CLOSE} was pressed 3 times")

    def test_a_tab_is_read_only_once_it_has_had_time_to_draw(self):
        self.run_screens([GUIDE_READY] * daily.SETTLE)
        self.assertEqual([], self.task.clicks)

    def test_a_move_under_a_claim_reward_is_never_pressed(self):
        self.run_screens([GUIDE_READY + (("Move", 0.391, 0.854),)] * SETTLED)
        self.assertEqual([], self.task.clicks)
        self.assertStopped("would have pressed 'Move'")

    def test_a_move_under_the_stage_ring_is_never_pressed(self):
        """The ring is pressed at its fixed point, with no OCR box of its own, so only the boxes under that point can refuse it."""
        texts, frame = GUIDE_STAGE_READY
        self.run_screens([(texts + (("Move", *daily.TARGETS[daily.STAGE_CLAIM]),), frame)] * SETTLED)
        self.assertEqual([], self.task.clicks)
        self.assertStopped(f"{daily.STAGE_CLAIM} would have pressed 'Move'")

    def test_a_move_under_the_log_claim_is_never_pressed(self):
        """The log's claim is a fixed point too, refused by the box under it."""
        texts, frame = LOG_READY
        self.state()["claims"]["phase"] = daily.ACTIVITY_PHASES.index(daily.LOG)
        self.run_screens([(texts + (("Move", *daily.TARGETS[daily.LOG_CLAIM]),), frame)] * SETTLED)
        self.assertEqual([], self.task.clicks)
        self.assertStopped(f"{daily.LOG_CLAIM} would have pressed 'Move'")

    def test_the_mission_records_shop_under_a_goal_stops_daily(self):
        texts, frame = WEEKLY_GOAL_READY
        self.state()["claims"]["phase"] = daily.ACTIVITY_PHASES.index(daily.WEEKLY)
        self.run_screens([(texts + (("Mission Records Shop", 0.388, 0.869),), frame)] * SETTLED)
        self.assertEqual([], self.task.clicks)
        self.assertStopped("would have pressed 'Mission Records Shop'")

    def test_two_claims_in_a_row_that_open_nothing_stop(self):
        """A daily Claim All that stays orange and opens nothing: pressed, retried once, then Daily stops."""
        self.state()["claims"]["phase"] = daily.ACTIVITY_PHASES.index(daily.SCHEDULE)
        self.run_screens([SCHEDULE_READY] * (SETTLED + 2 * daily.CLAIM_WAIT))
        self.assertPressed(daily.SCHEDULE_CLAIM, daily.SCHEDULE_CLAIM)
        self.assertStopped("two claims in a row opened nothing")

    def test_a_goal_that_stays_in_its_row_counts_as_a_claim_that_opened_nothing(self):
        """Neither the progress nor the goals changed: one claim that opened nothing, and the goal pressed once more."""
        self.state()["claims"]["phase"] = daily.ACTIVITY_PHASES.index(daily.WEEKLY)
        self.run_screens([WEEKLY_GOAL_READY] * (SETTLED + daily.CLAIM_WAIT))
        self.assertPressed(daily.GOAL_CLAIM, daily.GOAL_CLAIM)
        self.assertEqual(1, self.state()["claims"]["misses"])
        self.assertEqual(0, self.state()["claims"]["claimed"]["goal"])

    def test_a_claim_that_keeps_coming_back_stops_at_its_cap(self):
        """The log's top row still orange after two claims, each with its Items Obtained: the third press is refused."""
        self.state()["claims"]["phase"] = daily.ACTIVITY_PHASES.index(daily.LOG)
        self.run_screens(([LOG_READY] * SETTLED + [CLAIM_ITEMS]) * 2 + [LOG_READY] * SETTLED)
        self.assertPressed(daily.LOG_CLAIM, daily.ITEMS_CLOSE, daily.LOG_CLAIM, daily.ITEMS_CLOSE)
        self.assertStopped(f"{daily.LOG_CLAIM} was pressed 2 times")

    def test_the_presses_that_opened_a_claim_screen_count_only_until_it_shows(self):
        """A later step opens the menu again, and the presses that got the screen open were not stuck ones."""
        cases = ((GUIDE_READY, (daily.MENU, daily.ACTIVITY)), (ACHIEVEMENT_CARDS, (daily.MENU, daily.ACHIEVEMENT_ENTRY)),
                 (CATEGORY_JOURNEY, (daily.MENU, daily.ACHIEVEMENT_ENTRY, daily.JOURNEY_CARD)))
        for screen, targets in cases:
            for target in targets:
                with self.subTest(screen=screen[0][0], target=target):
                    self.task = Task()
                    self.on_step("activity")
                    self.state()["taps"][target] = daily.TAP_LIMITS[target]
                    run_pass(self.task.show(screen))
                    self.assertEqual(0, self.state()["taps"][target])

    def test_off_the_activity_step_the_window_is_only_closed(self):
        self.finish_chores()
        self.run_screens([GUIDE_READY, SCHEDULE_READY])
        self.assertPressed(daily.ACTIVITY_CLOSE)

    def test_negative_control_without_the_colour_checks_greyed_tabs_get_pressed(self):
        """Proves the greyed patches are what keep the claims unpressed in the nothing-to-claim route."""
        with mock.patch.object(daily, "face_share", lambda *args: 1.0):
            self.run_screens([GUIDE_NOTHING] * SETTLED)
        self.assertPressed(daily.STAGE_CLAIM)


class TestAchievementScreen(Claims):

    def setUp(self):
        super().setUp()
        self.on_step("achievement")

    def test_each_category_s_claim_all_is_pressed_while_blue_then_back_to_the_lobby(self):
        """Four categories with something ready: one Claim All each, counted afresh per category, and each Items Obtained closed."""
        lit = placed("achievement_claim_all_lit", CATEGORY_CROP)
        screens = [ACHIEVEMENT_CARDS]
        for ready, done in zip((CATEGORY_JOURNEY, CATEGORY_EXPLORATION, CATEGORY_TRACES, CATEGORY_OVERCOMING), CATEGORIES_NOTHING):
            screens += [(ready, lit)] * SETTLED + [CLAIM_ITEMS] + [done] * SETTLED
        self.run_screens(screens + [ACHIEVEMENT_CARDS, LOBBY])
        claim = (daily.CATEGORY_CLAIM, daily.ITEMS_CLOSE)
        self.assertPressed(daily.JOURNEY_CARD, *claim, daily.CATEGORY_TABS[1], *claim, daily.CATEGORY_TABS[2], *claim, daily.CATEGORY_TABS[3], *claim,
                           daily.CATEGORY_LEAVE, daily.CARDS_LEAVE, daily.MENU)
        self.assertEqual(0, self.task.disabled)
        self.assertEqual(4, self.state()["claims"]["claimed"]["category"])

    def test_a_grey_claim_all_is_never_pressed(self):
        self.run_screens([ACHIEVEMENT_CARDS] + [screen for screen in CATEGORIES_NOTHING for _ in range(SETTLED)])
        self.assertPressed(daily.JOURNEY_CARD, *daily.CATEGORY_TABS[1:], daily.CATEGORY_LEAVE)
        self.assertEqual(daily.DONE, self.state()["steps"]["achievement"])

    def test_off_the_step_both_screens_only_go_back(self):
        self.finish_chores()
        self.run_screens([CATEGORY_READY, ACHIEVEMENT_CARDS])
        self.assertPressed(daily.CATEGORY_LEAVE, daily.CARDS_LEAVE)

    def test_a_back_arrow_that_does_nothing_stops_at_its_cap(self):
        self.finish_chores()
        self.run_screens([CATEGORY_READY] * (3 * daily.NAV_WAIT + 1))
        self.assertPressed(daily.CATEGORY_LEAVE, daily.CATEGORY_LEAVE, daily.CATEGORY_LEAVE)
        self.assertStopped(f"{daily.CATEGORY_LEAVE} was pressed 3 times")


class TestClaimsInTheRun(Claims):

    def test_mail_then_the_claims_then_the_park_and_the_finish_line_names_each_claim(self):
        self.run_screens([LOBBY, MENU, (MAIL, claim_all(lit=True)), ITEMS, (MAIL_AFTER, claim_all(lit=False)), LOBBY, MENU]
                         + [GUIDE_READY] * SETTLED + [CLAIM_ITEMS] + [GUIDE_NOTHING] * SETTLED + [SCHEDULE_READY] * SETTLED + [CLAIM_ITEMS]
                         + [SCHEDULE_NOTHING] * SETTLED + [WEEKLY_NOTHING] * SETTLED + [LOG_NOTHING] * SETTLED
                         + [LOBBY, MENU, ACHIEVEMENT_CARDS] + [CATEGORY_READY] * SETTLED + [CLAIM_ITEMS]
                         + [screen for screen in CATEGORIES_NOTHING for _ in range(SETTLED)] + [ACHIEVEMENT_CARDS, LOBBY] + NO_PARK_ROUTE + [LOBBY])
        self.assertPressed(daily.MENU, daily.ENVELOPE, daily.CLAIM_ALL, daily.ITEMS_CLOSE, daily.MAIL_CLOSE, daily.MENU, daily.ACTIVITY,
                           daily.GUIDE_CLAIM, daily.ITEMS_CLOSE, daily.SCHEDULE_TAB, daily.SCHEDULE_CLAIM, daily.ITEMS_CLOSE, daily.WEEKLY_TAB,
                           daily.LOG_TAB, daily.ACTIVITY_CLOSE, daily.MENU, daily.ACHIEVEMENT_ENTRY, daily.JOURNEY_CARD, daily.CATEGORY_CLAIM,
                           daily.ITEMS_CLOSE, *daily.CATEGORY_TABS[1:], daily.CATEGORY_LEAVE, daily.CARDS_LEAVE, daily.MENU,
                           *NO_PARK_ROUTE_PRESSES)
        self.assertNothingForbidden()
        self.assertStopped("Daily finished: mail claimed; Dream Park is not running; Activity: 1 Growth Guide card, Claim All on the daily schedule; "
                           "Achievements: Claim All in 1 category; Nightmare Carnival is not running; The Path of a Captain: nothing to claim.")

    def test_negative_control_everything_greyed_presses_only_the_tabs_the_card_and_the_exits(self):
        self.on_step("activity")
        self.run_screens([LOBBY] + NOTHING_TO_CLAIM)
        self.assertPressed(daily.MENU, *NOTHING_TO_CLAIM_PRESSES)
        self.assertNothingForbidden()
        self.assertEqual(0, self.task.disabled)
        self.finish_chores()
        run_pass(self.task.show(LOBBY))
        self.assertStopped("Activity: nothing to claim; Achievements: nothing to claim; Nightmare Carnival is not running.")

    def test_a_menu_whose_activity_does_not_read_presses_nothing_and_counts_as_unknown(self):
        self.on_step("activity")
        unread = tuple(box for box in MENU if box[0] != "Activity")
        self.run_screens([unread] * (daily.UNKNOWN_SECONDS + 1))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Daily does not know this screen")


CARNIVAL_PENDING = (CARNIVAL, placed("daily_carnival_days_pending", CARNIVAL_CROP))
CARNIVAL_CLAIMED = (CARNIVAL_AFTER, placed("daily_carnival_days_claimed", CARNIVAL_CROP))
CARNIVAL_ON_EXCHANGE = (CARNIVAL_EXCHANGE, placed("daily_carnival_exchange_bottom", CARNIVAL_CROP))
# The pending bar's violet, HSV (133, 148, 215), as a BGR pixel.
BAR_VIOLET = cv2.cvtColor(np.uint8([[[133, 148, 215]]]), cv2.COLOR_HSV2BGR)[0, 0]


def bar_frame(*spans, colour=BAR_VIOLET):
    """Give a frame with blocks of one colour where the Carnival's day bars sit, x spans as fractions."""
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for left, right in spans:
        frame[int(0.872 * HEIGHT):int(0.915 * HEIGHT), int(left * WIDTH):int(right * WIDTH)] = colour
    return frame


class TestCarnival(Claims):

    def setUp(self):
        super().setUp()
        self.on_step("carnival")

    def test_the_lobby_s_banner_opens_the_carnival(self):
        self.assertTrue(run_pass(self.task.show(LOBBY_CARNIVAL)))
        self.assertPressed(daily.CARNIVAL_BANNER)

    def test_a_lobby_without_the_banner_skips_the_chore_and_goes_on_to_the_park(self):
        self.assertTrue(run_pass(self.task.show(LOBBY)))
        self.assertPressed(daily.MENU)
        self.assertEqual(daily.DONE, self.state()["steps"]["carnival"])
        self.assertEqual(0, self.task.disabled)
        self.assertIn("Nightmare Carnival is not running", daily.claims_summary(self.state()["claims"]))

    def test_another_banner_in_its_place_is_never_tapped(self):
        """Once the event ends another banner takes its spot, and no date keeps the old spot tapped."""
        self.assertTrue(run_pass(self.task.show(edited_text(LOBBY_CARNIVAL, "Nightmare Carnival", "Blazebell Rate up"))))
        self.assertPressed(daily.MENU)

    def test_every_pending_day_is_claimed_with_one_press_and_counted_from_the_bars_that_left(self):
        """Days 3 to 5 pending, one press on day 3, Items Obtained, then every reached day claimed."""
        self.run_screens([CARNIVAL_PENDING] * SETTLED + [CARNIVAL_ITEMS] + [CARNIVAL_CLAIMED] * SETTLED + [LOBBY])
        self.assertPressed(daily.CARNIVAL_DAY, daily.ITEMS_CLOSE, daily.CARNIVAL_LEAVE, daily.MENU)
        self.assertNothingForbidden()
        self.assertEqual(0, self.task.disabled)
        self.assertEqual(3, self.state()["claims"]["claimed"]["carnival"])
        self.assertIn("Carnival: 3 attendance days", daily.claims_summary(self.state()["claims"]))

    def test_with_every_day_claimed_no_day_is_pressed(self):
        self.run_screens([CARNIVAL_CLAIMED] * SETTLED)
        self.assertPressed(daily.CARNIVAL_LEAVE)
        self.assertIn("Carnival: nothing to claim", daily.claims_summary(self.state()["claims"]))

    def test_the_window_is_told_by_its_text_and_given_time_before_any_press(self):
        self.run_screens([CARNIVAL_PENDING] * daily.SETTLE)
        self.assertEqual([], self.task.clicks)
        texts, frame = CARNIVAL_PENDING
        unread = tuple(box for box in texts if box[0] not in ("Nightmare Carnival", "Attendance Check"))
        self.assertFalse(daily.handle_daily_carnival(self.task.show(unread, frame)))
        self.assertEqual([], self.task.clicks)

    def test_a_window_that_does_not_read_is_left_with_a_note_and_daily_goes_on(self):
        """Under a popup or after an OCR miss only the title or only the tab label reads: no day press and no stop, just the
        back arrow once the window has had time, a note on the finish line, and the park's Menu next."""
        texts, frame = CARNIVAL_PENDING
        for caption in ("Attendance Check", "Nightmare Carnival"):
            with self.subTest(missing=caption):
                self.task = Task()
                self.on_step("carnival")
                unread = (tuple(box for box in texts if box[0] != caption), frame)
                self.run_screens([LOBBY_CARNIVAL] + [unread] * (daily.CARNIVAL_UNREAD_WAIT + 1) + [LOBBY])
                self.assertPressed(daily.CARNIVAL_BANNER, daily.CARNIVAL_LEAVE, daily.MENU)
                self.assertNothingForbidden()
                self.assertEqual(0, self.task.disabled)
                self.assertEqual(daily.DONE, self.state()["steps"]["carnival"])
                self.assertIn("Carnival: its window did not read", daily.claims_summary(self.state()["claims"]))

    def test_on_another_tab_attendance_check_is_opened_and_make_up_and_go_are_never_pressed(self):
        self.run_screens([CARNIVAL_ON_EXCHANGE] * SETTLED + [CARNIVAL_PENDING] * SETTLED + [CARNIVAL_ITEMS] + [CARNIVAL_CLAIMED] * SETTLED)
        self.assertPressed(daily.CARNIVAL_TAB, daily.CARNIVAL_DAY, daily.ITEMS_CLOSE, daily.CARNIVAL_LEAVE)
        self.assertNothingForbidden()

    def test_a_tab_that_will_not_open_ends_the_chore_without_a_stop(self):
        self.run_screens([CARNIVAL_ON_EXCHANGE] * (SETTLED + 2 * daily.NAV_WAIT))
        self.assertPressed(daily.CARNIVAL_TAB, daily.CARNIVAL_TAB, daily.CARNIVAL_LEAVE)
        self.assertEqual(0, self.task.disabled)
        self.assertIn("Carnival: its Attendance Check did not open", daily.claims_summary(self.state()["claims"]))

    def test_a_make_up_or_go_under_the_day_point_stops_daily_with_nothing_pressed(self):
        texts, frame = CARNIVAL_PENDING
        for word in ("Check-In Make-Up", "Go"):
            with self.subTest(word=word):
                self.task = Task()
                self.on_step("carnival")
                self.run_screens([(texts + ((word, *POINTS[daily.CARNIVAL_DAY]),), frame)] * SETTLED)
                self.assertEqual([], self.task.clicks)
                self.assertStopped(f"{daily.CARNIVAL_DAY} would have pressed {word!r}")

    def test_off_the_chore_the_window_is_only_left(self):
        self.finish_chores()
        self.run_screens([CARNIVAL_PENDING])
        self.assertPressed(daily.CARNIVAL_LEAVE)

    def test_the_open_menu_with_the_carnival_next_is_closed(self):
        self.assertTrue(run_pass(self.task.show(MENU)))
        self.assertPressed(daily.MENU_CLOSE)

    def test_a_faded_lobby_with_the_carnival_next_gets_the_wake_tap_not_a_guess_at_the_banner(self):
        self.state()["lobby_seen"] = self.clock.now
        self.tick()
        self.assertTrue(run_pass(self.task.show(FADED, faded_lobby())))
        self.assertPressed(daily.WAKE)

    def test_the_pending_days_are_read_off_their_violet_bars(self):
        days = daily.pending_days(self.task.show(*CARNIVAL_PENDING))
        self.assertEqual(3, len(days))
        self.assertAlmostEqual(POINTS[daily.CARNIVAL_DAY][0], (days[0][0] + days[0][1]) / 2, delta=0.005)
        for screen in (CARNIVAL_CLAIMED, CARNIVAL_ON_EXCHANGE):
            self.assertEqual([], daily.pending_days(self.task.show(*screen)))
        self.assertEqual([], daily.pending_days(self.task.show(CARNIVAL)))

    def test_a_bar_cut_at_the_list_s_edge_or_drawn_white_is_no_pending_day(self):
        self.assertEqual([], daily.pending_days(self.task.show(CARNIVAL, bar_frame((0.229, 0.242)))))
        self.assertEqual([], daily.pending_days(self.task.show(CARNIVAL, bar_frame((0.30, 0.40), colour=(255, 255, 255)))))
        self.assertEqual(1, len(daily.pending_days(self.task.show(CARNIVAL, bar_frame((0.229, 0.242), (0.30, 0.40))))))


class TestCaptain(Claims):

    def setUp(self):
        super().setUp()
        self.to_park()
        self.state()["claims"]["captain"] = None

    def test_the_event_list_opens_the_path_of_a_captain_before_dream_park(self):
        self.assertTrue(run_pass(self.task.show(EVENT_LIST)))
        self.assertPressed(daily.CAPTAIN_ENTRY)

    def test_a_reached_tier_is_claimed_counted_and_dream_park_opened_next(self):
        """The Lv 20 tier's Claim Reward, Items Obtained, then the tier reads Claimed."""
        self.run_screens([CAPTAIN] * SETTLED + [CAPTAIN_ITEMS] + [CAPTAIN_AFTER] * SETTLED)
        self.assertPressed(daily.CAPTAIN_CLAIM, daily.ITEMS_CLOSE, daily.DREAM_PARK)
        self.assertNothingForbidden()
        self.assertEqual(1, self.state()["claims"]["claimed"]["captain"])
        self.assertIn("The Path of a Captain: 1 tier", daily.claims_summary(self.state()["claims"]))

    def test_claimed_and_locked_tiers_are_never_pressed(self):
        self.run_screens([CAPTAIN_AFTER] * SETTLED)
        self.assertPressed(daily.DREAM_PARK)
        self.assertIn("The Path of a Captain: nothing to claim", daily.claims_summary(self.state()["claims"]))

    def test_a_list_without_it_goes_on_to_dream_park(self):
        self.run_screens([tuple(box for box in EVENT_LIST if "Path of a" not in box[0])] * SETTLED)
        self.assertPressed(daily.DREAM_PARK)
        self.assertEqual("not listed", self.state()["claims"]["captain"])
        self.assertNotIn("Path of a Captain", daily.claims_summary(self.state()["claims"]))

    def test_a_move_under_a_claim_reward_is_never_pressed(self):
        self.run_screens([CAPTAIN + (("Move", *POINTS[daily.CAPTAIN_CLAIM]),)] * SETTLED)
        self.assertEqual([], self.task.clicks)
        self.assertStopped("would have pressed 'Move'")

    def test_off_the_park_step_its_page_is_only_left(self):
        self.finish_chores()
        self.run_screens([CAPTAIN])
        self.assertPressed(daily.EVENT_LEAVE)


TWO_GOALS_READY = (WEEKLY_TWO_GOALS, composed(("activity_goals_two_lit", GOALS_CROP), ("activity_milestones_two_claimed", MILESTONES_CROP)))
TWO_TIERS_READY = (WEEKLY_TWO_TIERS, composed(("activity_goals_two_gone", GOALS_CROP), ("activity_milestones_two_lit", MILESTONES_CROP)))
TWO_TIERS_TAKEN = (WEEKLY_TIERS_TAKEN, composed(("activity_goals_two_gone", GOALS_CROP), ("activity_milestones_two_claimed", MILESTONES_CROP)))
THREE_LEVELS_READY = (LOG_THREE, placed("activity_log_three_rings", LOG_COLUMN_CROP))
THREE_LEVELS_TAKEN = (LOG_THREE_TAKEN, placed("activity_log_three_claimed", LOG_COLUMN_CROP))


class TestCountsFromTheScreen(Claims):
    """Captures where one press took two weekly goals, one took two milestone tiers, one took three Achievement Log levels."""

    def setUp(self):
        super().setUp()
        self.on_step("activity")
        self.state()["claims"]["phase"] = daily.ACTIVITY_PHASES.index(daily.WEEKLY)

    def test_the_live_presses_count_two_goals_two_tiers_and_three_levels(self):
        self.run_screens([TWO_GOALS_READY] * SETTLED + [TWO_TIERS_READY] * daily.CLAIM_WAIT + [MILESTONE_ITEMS] + [TWO_TIERS_TAKEN] * SETTLED
                         + [THREE_LEVELS_READY] * SETTLED + [CLAIM_ITEMS] + [THREE_LEVELS_TAKEN] * SETTLED)
        self.assertPressed(daily.GOAL_CLAIM, daily.MILESTONE_CLAIM, daily.ITEMS_CLOSE, daily.LOG_TAB, daily.LOG_CLAIM, daily.ITEMS_CLOSE,
                           daily.ACTIVITY_CLOSE)
        self.assertNothingForbidden()
        self.assertEqual({"goal": 2, "milestone": 2, "log": 3}, dict(self.state()["claims"]["claimed"]))
        self.assertTrue(daily.claims_summary(self.state()["claims"]).startswith(
            "Activity: 2 weekly goals, 2 weekly milestone tiers, 3 Achievement Log levels;"))

    def test_the_readers_count_what_is_ready(self):
        self.assertEqual(2, daily.goals_shown(self.task.show(*TWO_GOALS_READY)))
        self.assertEqual(2, daily.lit_milestones(self.task.show(*TWO_TIERS_READY)))
        self.assertEqual(0, daily.lit_milestones(self.task.show(*TWO_TIERS_TAKEN)))
        self.assertEqual(3, daily.log_rings(self.task.show(*THREE_LEVELS_READY)))
        self.assertEqual(0, daily.log_rings(self.task.show(*THREE_LEVELS_TAKEN)))
        self.assertEqual(0, daily.log_rings(self.task.show(LOG_THREE)))

    def test_a_count_off_its_own_screen_is_one(self):
        claims = self.state()["claims"]
        claims["recount"] = ("log", 3)
        daily.settle_recount(self.task.show(*THREE_LEVELS_TAKEN))
        self.assertEqual(1, claims["claimed"]["log"])
        self.assertIsNone(claims["recount"])

    def test_a_claim_that_reads_as_still_ready_counts_one(self):
        """Items Obtained showed, so something was taken, even when as many read ready as before."""
        claims = self.state()["claims"]
        claims["recount"] = ("log", 3)
        daily.settle_recount(self.task.show(*THREE_LEVELS_READY), ("log",))
        self.assertEqual(1, claims["claimed"]["log"])

    def test_the_finish_line_words_each_claim(self):
        """Claim All takes every ready row at once, which no screen counts, so it is told as presses."""
        claims = daily.new_claims()
        claims["claimed"].update(guide=1, schedule=2, goal=2, milestone=2, log=3, category=4, carnival=3, captain=1)
        claims["carnival"], claims["captain"] = "visited", "visited"
        self.assertEqual("Activity: 1 Growth Guide card, Claim All on the daily schedule 2 times, 2 weekly goals, 2 weekly milestone tiers, "
                         "3 Achievement Log levels; Achievements: Claim All in 4 categories; Carnival: 3 attendance days; "
                         "The Path of a Captain: 1 tier", daily.claims_summary(claims))


def stand_in(module):
    """Copy a module so an install edits the copy, its handler list included.

    Args:
        module: The real module.

    Returns:
        The copy, under the same name.
    """
    copy = types.ModuleType(module.__name__)
    copy.__dict__.update(vars(module))
    if isinstance(getattr(module, handlers.HANDLER_LIST, None), list):
        copy.PAGE_HANDLERS = list(PRISTINE if module is daily else module.PAGE_HANDLERS)
    return copy


def registered_installs():
    """Rebuild every handler-list edit the app registers, in the order `src/globals.py` applies the modules.

    Each `register(...)` inside a module's `apply` is evaluated in that module's own namespace, with any function `apply`
    defines for it, so the edits are the app's own without running the rest of `apply`, which patches the framework.

    Returns:
        The install callables.
    """
    source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
    installs = []
    for name in re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M):
        module = importlib.import_module(f"src.en.{name}")
        module_source = Path(module.__file__).read_text(encoding="utf-8")
        for node in ast.parse(module_source).body:
            if not (isinstance(node, ast.FunctionDef) and node.name == "apply"):
                continue
            namespace = dict(vars(module))
            for statement in node.body:
                if isinstance(statement, ast.FunctionDef):
                    exec(textwrap.dedent(ast.get_source_segment(module_source, statement, padded=True)), namespace)  # noqa: S102
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "register" and call.args:
                    installs.append(eval(ast.get_source_segment(module_source, call.args[0]), namespace))  # noqa: S307
    return installs


class TestHandlerList(unittest.TestCase):

    def test_after_every_install_daily_runs_remote_the_stuck_stop_the_rescue_stop_then_its_own_and_nothing_generic(self):
        """10: an upstream handler inserted with no mode named would otherwise reach Daily's list."""
        self.assertEqual([handler.__name__ for handler in OWN], [handler.__name__ for handler in PRISTINE])
        real = {name: sys.modules[name] for name, _ in handlers.each_list()}
        real.update({name: sys.modules[name] for name in ("utils", "utils_chaos", "utils_sortie", "utils_story", daily.__name__)})
        copies = {name: stand_in(module) for name, module in real.items()}
        installs = registered_installs()
        self.assertGreater(len(installs), 20)
        with mock.patch.dict(sys.modules, copies):
            for _ in range(INSTALLS):
                for install in installs:
                    install()
        names = [handler.__name__ for handler in copies[daily.__name__].PAGE_HANDLERS]
        self.assertEqual(["handle_remote", "stop_when_stuck"] + [handler.__name__ for handler in OWN], names)
        for name in FORBIDDEN:
            self.assertNotIn(name, names)
        self.assertIn("handle_non_battle_page", [handler.__name__ for handler in copies["utils_story"].PAGE_HANDLERS])

    def test_after_every_install_every_mode_runs_the_hold_first_and_the_stuck_stop_next_to_its_first_own_handler(self):
        """A held run takes no pass of the stop, so a still screen while held never ends it, and unheld the stop still comes first."""
        real = {name: sys.modules[name] for name, _ in handlers.each_list()}
        real.update({name: sys.modules[name] for name in ("utils", "utils_chaos", "utils_sortie", "utils_story", daily.__name__)})
        copies = {name: stand_in(module) for name, module in real.items()}
        with mock.patch.dict(sys.modules, copies):
            for _ in range(INSTALLS):
                for install in registered_installs():
                    install()
        first_own = {"utils_chaos": "handle_auto_stop", "utils_sortie": "handle_auto_stop", "utils_story": "handle_center_confirm",
                     daily.__name__: "handle_rescue_screen"}
        for mode, anchor in first_own.items():
            with self.subTest(mode=mode):
                names = [handler.__name__ for handler in copies[mode].PAGE_HANDLERS]
                self.assertEqual("handle_remote", names[0])
                self.assertEqual(1, names.count("stop_when_stuck"))
                self.assertLess(names.index("stop_when_stuck"), names.index(anchor))

    def test_daily_is_applied_before_claims(self):
        """claims wraps the lists as it finds them, so nothing Daily's list gets later would be named in the frame log."""
        source = (REPO_ROOT / "src" / "globals.py").read_text(encoding="utf-8")
        applied = re.findall(r"^\s*(\w+)\.apply\(\)", source, re.M)
        self.assertLess(applied.index("stuck_stop"), applied.index("daily"))
        self.assertLess(applied.index("daily"), applied.index("claims"))

    def test_daily_is_built_from_the_config_as_a_trigger_task(self):
        """The shell gives every trigger task a Start button."""
        from src.config import config

        self.assertIn(["src.en.daily", "DailyMode"], config["trigger_tasks"])
        self.assertTrue(issubclass(daily.DailyMode, TriggerTask))

    def test_daily_imports_nothing_from_ok_tasks_at_import(self):
        """ok-script builds it before `ok_tasks/` is on `sys.path`."""
        tree = ast.parse((REPO_ROOT / "src" / "en" / "daily.py").read_text(encoding="utf-8"))
        tasks = {path.stem for path in (REPO_ROOT / "ok_tasks").glob("*.py")}
        for node in tree.body:
            if isinstance(node, ast.Import):
                self.assertFalse({alias.name.split(".")[0] for alias in node.names} & tasks)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], tasks)


class Mode:
    """Another mode of the app, enabled and stopped as the executor would."""

    def __init__(self, journal):
        self.journal = journal
        self.enabled = False

    def enable(self):
        self.enabled = True
        self.journal.append(("enable", type(self).__name__))

    def disable(self):
        self.enabled = False
        self.journal.append(("disable", type(self).__name__))


class ChaosMode(Mode):
    pass


class SortieMode(Mode):
    pass


class StoryMode(Mode):
    pass


class TestOneModeAtATime(unittest.TestCase):

    def setUp(self):
        self.journal = []
        self.others = [ChaosMode(self.journal), SortieMode(self.journal), StoryMode(self.journal)]
        self.daily = daily.DailyMode.__new__(daily.DailyMode)
        self.daily._enabled = False
        self.daily._executor = Executor(self.daily, *self.others)
        journal = self.journal

        def enable(task):
            task._enabled = True
            journal.append(("enable", type(task).__name__))

        def disable(task):
            task._enabled = False
            journal.append(("disable", type(task).__name__))

        for name, replacement in (("enable", enable), ("disable", disable)):
            patcher = mock.patch.object(TriggerTask, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_starting_daily_stops_whichever_mode_runs(self):
        for other in self.others:
            with self.subTest(mode=type(other).__name__):
                other.enabled = True
                self.journal.clear()
                self.daily.enable()
                self.assertEqual([("disable", type(other).__name__), ("enable", "DailyMode")], self.journal)
                self.assertFalse(other.enabled)

    def test_starting_another_mode_stops_daily(self):
        """11: through `load_config`, which the run loop and the debug port's `set_running` both start the mode after."""
        load_config = daily.teaching_modes(lambda task: None)
        for other in self.others:
            with self.subTest(mode=type(other).__name__):
                other.executor = self.daily._executor
                load_config(other)
                self.daily._enabled = True
                self.journal.clear()
                other.enable()
                self.assertEqual([("disable", "DailyMode"), ("enable", type(other).__name__)], self.journal)
                self.assertFalse(self.daily.enabled)

    def test_daily_itself_and_other_tasks_are_not_wrapped(self):
        load_config = daily.teaching_modes(lambda task: None)
        original = self.daily.enable
        load_config(self.daily)
        self.assertNotIn("enable", vars(self.daily))
        self.assertEqual(original, self.daily.enable)

    def test_a_start_begins_the_run_afresh_and_a_stop_forgets_it(self):
        state = daily.run_state(self.daily)
        state["steps"]["mail"] = daily.DONE
        self.daily.enable()
        self.assertEqual(daily.PENDING, daily.run_state(self.daily)["steps"]["mail"])
        self.daily.disable()
        self.assertNotIn(daily.RUN, vars(self.daily))


class TestStuckStopReachesDaily(unittest.TestCase):

    def test_the_stuck_stop_goes_after_remote_and_ahead_of_the_rescue_stop_once(self):
        module = types.ModuleType(daily.__name__)
        module.PAGE_HANDLERS = [types.SimpleNamespace(__name__="handle_remote")] + list(PRISTINE)
        fake_utils = types.SimpleNamespace(is_frame_stuck=lambda task, stuck_threshold_seconds=0: False)
        with mock.patch.dict(sys.modules, {daily.__name__: module}):
            for _ in range(INSTALLS):
                stuck_stop.install(fake_utils)
        self.assertEqual(["handle_remote", "stop_when_stuck", "handle_rescue_screen"], [handler.__name__ for handler in module.PAGE_HANDLERS[:3]])
        self.assertEqual(len(PRISTINE) + 2, len(module.PAGE_HANDLERS))


if __name__ == "__main__":
    unittest.main()
