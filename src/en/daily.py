"""Run the daily chores from the Lobby: close its popups, claim attendance, mail, Activity rewards, achievements and the Carnival's attendance, visit Dream Park, invest in the goal Combatants, stop on the Lobby.

The Lobby, its menu and the Mail screen sit next to buttons that delete mail, open the Shop, refill Aether with Crystals,
open Rescue or quit the game. So Daily presses only the fixed targets in `TARGETS`, each on the one screen it belongs to,
every press goes through `press`, which refuses a box that reads as any of those, and each target has a per-run limit.
A screen Daily does not know for 30 seconds, and the tutorial, stop it with nothing pressed.

The Activity window and the Achievement screen pay out for free, one tap per claim. A claim is pressed only while its
button reads ready, by its caption or its orange or blue face, never a `Move` that leaves the window, and two claims in
a row that open nothing stop Daily. The Activity window's two unlabelled middle tabs are never pressed. While the
Lobby shows the Nightmare Carnival's banner, one press on a pending attendance day claims every pending day; without
the banner the chore is skipped. The Event list visit opens The Path of a Captain first and claims each reached tier.
The finish line counts what left the screen where that reads reliably, and the presses where it does not.

The park spends only its own profit, a free counter that refills while the player is away. Its rows are read by
`dream_park`, and one is pressed only when its price reads as a plain park number. When the ride it wants is further
down, the list is dragged a short way, a few times a visit at most. Once a visit, the panel's Skill tab gets AI Automation
upgraded while one level pays for itself by the next visit, then Another Happy Day while Happiness lags, and no other
skill is ever pressed.

With a goal list set, the last chore invests in the listed Combatants, one at a time in the list's order, from materials
the account already holds: a Promotion, Level Up to the cap, the assigned Partner's Promotion and Level Up, Potential node
01 on each and node 02 on the first. `invest` reads every panel, and a spend is pressed only when its button reads the go
word on the same pass as a met counter and a Units cost that leaves the Units to keep. What each one is still short of is
written to `invest.GOALS_FILE`. Nothing is merged, replenished, bought or dismantled.

Imported by ok-script before `ok_tasks/` is on `sys.path`, so upstream is reached only through `handlers.loaded`.
"""

import math
import re
import time
from collections import Counter, namedtuple
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from ok import Logger, TriggerTask
from ok.device.interaction_methods.post_message import PostMessageInteraction

from src.en import dream_park, invest
from src.en.handlers import loaded
from src.en.runs import stop
from src.en.screen import centre_of, colour_share, frame_of, hsv_of, in_region, patch_of, text_in_region
from src.en.dialog_ticks import UNTICKED, box_state
from src.en.game_data import COMBATANTS
from src.en.spend_guard import (ACCOUNT, DELETION, MONEY, PURCHASE, RESCUE_HEADER, RESCUE_PHRASES, RETREAT, COMPACT_SKIP_DIALOG, cleaned,
                                folded, handle_rescue_screen, marker_in, shown)
from src.en.story import AFTER_TAP, SKIP_IMAGE, SKIP_MATCH, find_icon, grey, tap

logger = Logger.get_logger(__name__)

# The modes Daily may never run beside. Their own `enable`s know nothing of Daily, so `apply` teaches them.
OTHER_MODES = ("ChaosMode", "SortieMode", "StoryMode")

# What Daily presses, by name. A point is fixed by the screen's layout; None is a text button, pressed on the box OCR read.
BANNER_CLOSE = "the entry banner's X"
NOTICE_CLOSE = "the Notice board's X"
MENU = "the Lobby's Menu"
ENVELOPE = "the menu's Mail"
MENU_CLOSE = "the menu's X"
CLAIM_ALL = "Claim All"
ITEMS_CLOSE = "the Items Obtained caption"
MAIL_CLOSE = "the Mail popup's X"
WAKE = "the faded Lobby's sky"
EVENT = "the menu's Event"
DREAM_PARK = "the Event list's Dream Park"
EVENT_LEAVE = "the Event list's back arrow"
ENTER_PARK = "Enter Amusement Park"
PARK_ACHIEVEMENTS = "the event page's Achievements"
PAGE_LEAVE = "the event page's back arrow"
PARK_MANAGE = "the park's Manage"
PARK_OPERATE = "the park's Operate"
PANEL_CLOSE = "the park panel's back arrow"
PARK_LEAVE = "the park's back arrow"
PARK_RANK = "Amusement Park Rank"
RANK_UP = "Rank Up"
RANK_CLOSE = "the Rank screen's X"
RANK_RESULT_CLOSE = "the Rank result's caption"
UPGRADE = "a ride's Upgrade"
BUILD = "a ride's Build"
CLAIM = "an achievement's claim ring"
MANAGEMENT_TAB = "the Achievements' Management tab"
ACHIEVEMENTS_LEAVE = "the Achievements' back arrow"
RULES_CANCEL = "the Rules of Good Order's 取消"
PROFIT_CLOSE = "the Profit Report's caption"
STORY_SKIP = "the story bar's Skip"
SKIP_TICK = "the skip dialog's Do not show box"
SKIP_CONFIRM = "the skip dialog's 确认"
ATTENDANCE_CLAIM = "the attendance popup's Claim Reward"
ATTENDANCE_CLOSE = "the attendance popup's X"
SKILL_TAB = "the park panel's Skill tab"
FACILITIES_TAB = "the park panel's Facilities tab"
SKILL_UPGRADE = "AI Automation's Upgrade"
HAPPY_DAY_UPGRADE = "Another Happy Day's Upgrade"
ACTIVITY = "the menu's Activity"
GUIDE_TAB = "the Activity window's Growth Guide tab"
SCHEDULE_TAB = "the Activity window's daily schedule tab"
WEEKLY_TAB = "the Activity window's weekly schedule tab"
LOG_TAB = "the Activity window's Achievement Log tab"
ACTIVITY_CLOSE = "the Activity window's X"
GUIDE_CLAIM = "a Growth Guide card's Claim Reward"
STAGE_CLAIM = "the Growth Guide's stage reward"
SCHEDULE_CLAIM = "the daily schedule's Claim All"
GOAL_CLAIM = "a weekly goal's Goal Achieved"
MILESTONE_CLAIM = "a weekly milestone"
LOG_CLAIM = "the Achievement Log's claim"
ACHIEVEMENT_ENTRY = "the menu's Achievement"
JOURNEY_CARD = "the Achievement screen's Journey Log card"
CATEGORY_TABS = ("the Achievement screen's Journey Log tab", "the Achievement screen's Exploration Attitude tab",
                 "the Achievement screen's Traces of Obliteration tab", "the Achievement screen's Overcoming Adversity tab")
CATEGORY_CLAIM = "an achievement category's Claim All"
CARDS_LEAVE = "the Achievement screen's back arrow"
CATEGORY_LEAVE = "an achievement category's back arrow"
CARNIVAL_BANNER = "the Lobby's Nightmare Carnival banner"
CARNIVAL_TAB = "the Carnival's Attendance Check tab"
CARNIVAL_DAY = "a pending Carnival attendance day"
CARNIVAL_LEAVE = "the Carnival's back arrow"
CAPTAIN_ENTRY = "the Event list's The Path of a Captain"
CAPTAIN_CLAIM = "a Path of a Captain tier's Claim Reward"
INVEST_ENTRY = "the Lobby's Combatants"
UNIT_CARD = "a goal Combatant's card"
LIST_LEAVE = "the Combatant List's back arrow"
DETAILS_LEAVE = "the Details screen's back arrow"
STATS_TAB = "the Details screen's Stats tab"
PARTNERS_TAB = "the Details screen's Partners tab"
POTENTIAL_TAB = "the Details screen's Potential tab"
OPEN_PROMOTION = "the Stats tab's Promotions"
OPEN_LEVEL_UP = "the Stats tab's Level Up"
PARTNER_UPGRADE = "the Partners tab's 强化"
PROMOTE = "a Promotions panel's Promotions"
AUTO_REGISTER = "the Level Up panel's Auto Register"
LEVEL_UP = "the Level Up panel's Level Up"
PANEL_LEAVE = "an upgrade panel's back arrow"
NODE_01_ENTRY = "Potential node 01"
NODE_02_ENTRY = "Potential node 02"
ACTIVATE = "a node panel's Activate"
NODE_LEAVE = "the node panel's back arrow"
RESULT_CLOSE = "an upgrade result's caption"
# Every Dream Park screen draws its back arrow at the same place, and each press of it takes one screen back. The
# Achievement screen draws its own there too.
BACK = (0.041, 0.046)
TARGETS = {
    BANNER_CLOSE: (0.968, 0.049),
    NOTICE_CLOSE: (0.911, 0.120),
    MENU: (0.959, 0.046),
    ENVELOPE: (0.962, 0.280),
    MENU_CLOSE: (0.961, 0.049),
    MAIL_CLOSE: (0.936, 0.093),
    WAKE: (0.300, 0.420),
    CLAIM_ALL: None,
    ITEMS_CLOSE: None,
    EVENT: (0.783, 0.088),
    DREAM_PARK: None,
    EVENT_LEAVE: BACK,
    ENTER_PARK: None,
    PARK_ACHIEVEMENTS: None,
    PAGE_LEAVE: BACK,
    PARK_MANAGE: (0.087, 0.294),
    PARK_OPERATE: (0.087, 0.473),
    PANEL_CLOSE: BACK,
    PARK_LEAVE: BACK,
    PARK_RANK: (0.804, 0.906),
    RANK_UP: None,
    RANK_CLOSE: (0.977, 0.137),
    RANK_RESULT_CLOSE: None,
    UPGRADE: None,
    BUILD: None,
    CLAIM: None,
    MANAGEMENT_TAB: (0.100, 0.270),
    ACHIEVEMENTS_LEAVE: BACK,
    RULES_CANCEL: None,
    PROFIT_CLOSE: None,
    STORY_SKIP: None,
    SKIP_TICK: (0.392, 0.532),
    SKIP_CONFIRM: None,
    ATTENDANCE_CLAIM: None,
    ATTENDANCE_CLOSE: (0.933, 0.127),
    SKILL_TAB: (0.892, 0.185),
    FACILITIES_TAB: (0.714, 0.185),
    SKILL_UPGRADE: None,
    HAPPY_DAY_UPGRADE: None,
    ACTIVITY: None,
    GUIDE_TAB: (0.057, 0.120),
    SCHEDULE_TAB: (0.057, 0.231),
    WEEKLY_TAB: (0.057, 0.340),
    LOG_TAB: (0.057, 0.680),
    ACTIVITY_CLOSE: (0.940, 0.115),
    GUIDE_CLAIM: None,
    STAGE_CLAIM: (0.873, 0.247),
    SCHEDULE_CLAIM: None,
    GOAL_CLAIM: None,
    MILESTONE_CLAIM: None,
    LOG_CLAIM: (0.800, 0.290),
    ACHIEVEMENT_ENTRY: None,
    JOURNEY_CARD: (0.141, 0.600),
    CATEGORY_TABS[0]: (0.111, 0.138),
    CATEGORY_TABS[1]: (0.111, 0.220),
    CATEGORY_TABS[2]: (0.111, 0.302),
    CATEGORY_TABS[3]: (0.111, 0.387),
    CATEGORY_CLAIM: None,
    CARDS_LEAVE: BACK,
    CATEGORY_LEAVE: BACK,
    CARNIVAL_BANNER: None,
    CARNIVAL_TAB: (0.120, 0.330),
    CARNIVAL_DAY: None,
    CARNIVAL_LEAVE: BACK,
    CAPTAIN_ENTRY: None,
    CAPTAIN_CLAIM: None,
    INVEST_ENTRY: None,
    UNIT_CARD: None,
    LIST_LEAVE: BACK,
    DETAILS_LEAVE: BACK,
    STATS_TAB: None,
    PARTNERS_TAB: None,
    POTENTIAL_TAB: None,
    OPEN_PROMOTION: None,
    OPEN_LEVEL_UP: None,
    PARTNER_UPGRADE: None,
    PROMOTE: None,
    AUTO_REGISTER: None,
    LEVEL_UP: None,
    PANEL_LEAVE: BACK,
    # The Potential map writes no caption on either node, so each is pressed at the point that opened it on the live
    # client: node 01 always, node 02 only while its counter reads just below, at (0.442, 0.887).
    NODE_01_ENTRY: (0.309, 0.814),
    NODE_02_ENTRY: (0.442, 0.835),
    ACTIVATE: None,
    NODE_LEAVE: BACK,
    RESULT_CLOSE: None,
}
# How many upgrades one park visit may press, one level each, so the cap only bounds a loop that has gone wrong, and how
# many achievement claims: the event has 23 achievements.
UPGRADE_CAP = 200
CLAIM_CAP = 30
# How many AI Automation presses one visit may make, and as many for Another Happy Day; the price rule and the Happiness
# still needed end them far sooner.
SKILL_CAP = 30
# How many short drags down the Facilities list each opening of it may make, and the whole visit: the list opens at its
# top after every Rank Up and Skill tab trip, and the lagging ride sat one drag down on each of four openings in one
# visit. Then how many down the Skill tab one trip may make, how far a name must move for a drag to count as having
# moved the list, and the seconds handed to ok-script's swipe, as the debug port hands them: 20 steps 10 ms apart.
SCROLL_CAP = 3
SCROLL_VISIT_CAP = 12
SKILL_SCROLL_CAP = 2
SCROLL_MOVED = 0.01
DRAG_DURATION = 2
# How often each target may be pressed in one run. Claim All, the wake tap, Rank Up and Claim Reward get one retry for a
# tap the game ignored, and the skip dialog's box is tapped once a run; the rest allow two retries for a screen slow to
# change. A target leading to another screen counts only until that screen shows (`ARRIVALS`), so a later step, or the
# next round of the park, may press it again. The Activity claims only bound a loop gone wrong: a Growth Guide stage has
# up to 10 cards and the next stage may have ready ones, and one milestone press took every reached tier. An achievement
# category's Claim All counts afresh for each category. One press on a Carnival day took every pending day, and The Path
# of a Captain has five tiers. The invest step's way between its screens counts afresh as each screen shows
# (`INVEST_ARRIVALS`), and its spends afresh for each goal unit, so each spend limit is that unit's own.
TAP_LIMITS = {BANNER_CLOSE: 3, NOTICE_CLOSE: 3, MENU: 3, ENVELOPE: 3, MENU_CLOSE: 3, MAIL_CLOSE: 3, WAKE: 2, CLAIM_ALL: 2, ITEMS_CLOSE: 3,
              EVENT: 3, DREAM_PARK: 3, EVENT_LEAVE: 3, ENTER_PARK: 3, PARK_ACHIEVEMENTS: 3, PAGE_LEAVE: 3, PARK_MANAGE: 3, PARK_OPERATE: 3,
              PANEL_CLOSE: 3, PARK_LEAVE: 3, PARK_RANK: 3, RANK_UP: 2, RANK_CLOSE: 3, RANK_RESULT_CLOSE: 3, UPGRADE: UPGRADE_CAP, BUILD: 3,
              CLAIM: CLAIM_CAP, MANAGEMENT_TAB: 3, ACHIEVEMENTS_LEAVE: 3, RULES_CANCEL: 3, PROFIT_CLOSE: 3, STORY_SKIP: 3, SKIP_TICK: 1,
              SKIP_CONFIRM: 3, ATTENDANCE_CLAIM: 2, ATTENDANCE_CLOSE: 3, SKILL_TAB: 3, FACILITIES_TAB: 3, SKILL_UPGRADE: SKILL_CAP,
              HAPPY_DAY_UPGRADE: SKILL_CAP, ACTIVITY: 3, GUIDE_TAB: 3, SCHEDULE_TAB: 3, WEEKLY_TAB: 3, LOG_TAB: 3, ACTIVITY_CLOSE: 3,
              GUIDE_CLAIM: 15, STAGE_CLAIM: 3, SCHEDULE_CLAIM: 2, GOAL_CLAIM: 6, MILESTONE_CLAIM: 2, LOG_CLAIM: 2, ACHIEVEMENT_ENTRY: 3,
              JOURNEY_CARD: 3, **{tab: 3 for tab in CATEGORY_TABS}, CATEGORY_CLAIM: 2, CARDS_LEAVE: 3, CATEGORY_LEAVE: 3,
              CARNIVAL_BANNER: 3, CARNIVAL_TAB: 2, CARNIVAL_DAY: 2, CARNIVAL_LEAVE: 3, CAPTAIN_ENTRY: 3, CAPTAIN_CLAIM: 6,
              INVEST_ENTRY: 3, UNIT_CARD: 3, LIST_LEAVE: 3, DETAILS_LEAVE: 3, STATS_TAB: 3, PARTNERS_TAB: 3, POTENTIAL_TAB: 3,
              OPEN_PROMOTION: 3, OPEN_LEVEL_UP: 3, PARTNER_UPGRADE: 3, PANEL_LEAVE: 3, NODE_01_ENTRY: 3, NODE_02_ENTRY: 3, NODE_LEAVE: 3,
              RESULT_CLOSE: 3, PROMOTE: 2, LEVEL_UP: 6, AUTO_REGISTER: 8, ACTIVATE: 10}
# What one goal unit may spend in a run: one Promotion for the Combatant and one for its Partner, three Level Up presses
# on each of their panels, and ten node levels in all.
LEVEL_CYCLES = 3
ACTIVATE_CAP = 10
TOWARD_MAIL = (MENU, ENVELOPE)

# What `press` refuses whatever it was asked to press: mail deletion, the Shop, a purchase, Crystals or any account
# currency, a real price, Rescue, and a retreat word such as the Escape that abandons an open run. Read off the box under
# the point, folded as the spend guard folds it.
REFUSED_GROUPS = (ACCOUNT, PURCHASE, DELETION, MONEY, RETREAT)
SHOP = ("shop", "商店")

# Each screen as `(left, top, right, bottom)` screen fractions around where its captions read on the Global client.
# The Lobby: Story where upstream's own Lobby stop reads it, at (0.884, 0.156), and Combatants at (0.867, 0.617). The open
# menu slides that column left, Story to (0.581, 0.091), so the Lobby never reads as itself under the menu.
LOBBY_STORY = ("故事", (0.85, 0.12, 0.92, 0.20))
LOBBY_COMBATANTS = ("Combatants", (0.82, 0.58, 0.92, 0.66))
# The open menu: Achievement at (0.808, 0.520) and Arkhianon Supply at (0.825, 0.160).
MENU_ACHIEVEMENT = ("Achievement", (0.76, 0.49, 0.86, 0.55))
MENU_SUPPLY = ("Arkhianon Supply", (0.77, 0.13, 0.88, 0.19))
# The Notice board's two tabs, at (0.216, 0.119) and (0.403, 0.119).
NOTICE_TAB = ("Notice", (0.15, 0.08, 0.30, 0.16))
UPDATE_TAB = ("Update", (0.33, 0.08, 0.47, 0.16))
# The Mail popup's title at (0.107, 0.090) and its `003 / 100` count at (0.844, 0.090). Its X sits 0.024 right of a
# column of three dots, and the envelope beside the title, which OCR reads as `√`, is no back arrow.
MAIL_TITLE = ("Mail", (0.06, 0.06, 0.16, 0.12))
MAIL_COUNT_REGION = (0.78, 0.06, 0.90, 0.12)
MAIL_COUNT = re.compile(r"\d{3}/100")
# Claim All, read at (0.194, 0.904). `Delete read mail` reads 0.19 to its right, so the band stops short of it.
CLAIM_ALL_REGION = (0.12, 0.86, 0.28, 0.95)
# Claim All's face between its icon and its caption: orange while there is mail to claim, a flat grey (195, 195, 195) once
# there is none. A press on the grey button opens nothing and only shows `All items in the mail have been received.`,
# centred at (0.500, 0.275).
CLAIM_ALL_FACE = (0.085, 0.880, 0.150, 0.925)
GREYED_LOW = np.array((0, 0, 150))
GREYED_HIGH = np.array((180, 30, 230))
GREYED_SHARE = 0.9
MAIL_EMPTY = ("All items in the mail have been received", (0.30, 0.22, 0.70, 0.33))
# Items Obtained's title at (0.502, 0.377) and its close caption at (0.501, 0.935), above the `进入` at (0.500, 0.978).
ITEMS_TITLE = ("Items Obtained", (0.40, 0.33, 0.60, 0.42))
ITEMS_CAPTION = ("点击屏幕关闭窗口", (0.40, 0.90, 0.60, 0.965))
# The daily attendance popup the game opens on the first Lobby of a game day: its title at (0.690, 0.169), `Permanent`
# under it at (0.833, 0.229), and seven day cards, today's showing an orange Claim Reward, at (0.459, 0.830) on day 4.
# Its X at (0.933, 0.127) is drawn before the claim too, though OCR reads it as `X` only after. The Event list's page
# for the same event reads the title at (0.774, 0.136) and `Permanent` at (0.918, 0.201), outside both regions.
ATTENDANCE_TITLE = ("Invitation to a New Journey", (0.60, 0.15, 0.76, 0.19))
ATTENDANCE_TAG = ("Permanent", (0.79, 0.21, 0.87, 0.25))
ATTENDANCE_CARDS = ("Claim Reward", (0.38, 0.25, 0.90, 0.90))
# The tutorial's Skip Tutorial pill, read at (0.879, 0.055) wherever it shows. Its outline spans x 0.818-0.992 and
# y 0.020-0.091, over the Lobby's Menu, the banner's X and the menu's X, and a tap on it skips the tutorial.
SKIP_TUTORIAL = ("Skip Tutorial", (0.0, 0.0, 1.0, 1.0))

# The entry banner shows no stable text, so it is told by its X with the three dots beside it, cut from a 1080p capture.
# The X scored 1.00 on the banner it was cut from; the plain X of a node or mission detail, at the same place, at most 0.835
# over 439 captures, and the Lobby and the open menu 0.21 at most.
BANNER_CLOSE_IMAGE = Path(__file__).with_name("images") / "lobby_banner_close.png"

# The Event list: its title at (0.109, 0.048) and the column heading at (0.091, 0.138). It opens on its first event, not
# the last one viewed. Dream Park's page: its title at (0.814, 0.167), Enter Amusement Park at (0.775, 0.901) and
# Achievements at (0.551, 0.900); the `New Event! [Rules of Good Order]` banner at (0.803, 0.803) is never pressed.
EVENT_TITLE = ("Event", (0.06, 0.02, 0.16, 0.08))
EVENT_HEADING = ("Recommended Events", (0.0, 0.10, 0.20, 0.17))
PARK_TITLE = ("Nightmare Dream Park", (0.70, 0.13, 0.93, 0.20))
PARK_ENTER = ("Enter Amusement Park", (0.68, 0.87, 0.87, 0.93))
PARK_ACHIEVEMENTS_BUTTON = ("Achievements", (0.48, 0.87, 0.62, 0.93))
# The park's left column, Manage at (0.087, 0.294) and Operate at (0.087, 0.473), drawn on the park view and beside each panel.
PARK_MANAGE_TAB = ("Manage", (0.03, 0.26, 0.14, 0.32))
PARK_OPERATE_TAB = ("Operate", (0.03, 0.44, 0.14, 0.50))
# The Manage panel: Visitor Emotions at (0.705, 0.633), Amusement Park Rank at (0.804, 0.906), and its title naming the
# Rank, `The Amusement Park All the Buzz Is About Rank 5` at (0.804, 0.313).
MANAGE_EMOTIONS = ("Visitor Emotions", (0.62, 0.60, 0.80, 0.66))
MANAGE_RANK = ("Amusement Park Rank", (0.72, 0.88, 0.89, 0.93))
MANAGE_TITLE_REGION = (0.65, 0.29, 0.97, 0.34)
RANK_NUMBER = re.compile(r"rank\s*(\d+)\s*$", re.I)
# The Facilities list: its title at (0.803, 0.274) and the hint under it at (0.802, 0.930).
FACILITIES_TITLE = ("Facilities", (0.75, 0.25, 0.86, 0.30))
FACILITIES_HINT = ("Press and hold", (0.70, 0.90, 0.90, 0.96))
# The same panel's Skill tab, opened on the star tab at (0.892, 0.185) beside Facilities' tent at (0.714, 0.185): its
# title at (0.803, 0.274) and the same hint under it.
SKILL_TITLE = ("技能", (0.75, 0.25, 0.86, 0.30))
# The Amusement Park Rank screen's title at (0.501, 0.137), and the result over it: `Rank 6 Achieved` at (0.500, 0.521)
# with its close caption at (0.500, 0.938).
RANK_TITLE = ("Amusement Park Rank", (0.40, 0.10, 0.60, 0.17))
RANK_ACHIEVED = re.compile(r"rank\s*\d+\s*achieved", re.I)
RANK_ACHIEVED_REGION = (0.35, 0.47, 0.65, 0.57)
RANK_CAPTION = ("点击屏幕关闭窗口", (0.40, 0.90, 0.60, 0.97))
# The event's achievements: `Event Special Rewards` at (0.184, 0.045); its second tab lists the ride-level rewards as
# `Reach [Merry-Go-Round] Level 50`.
ACHIEVEMENTS_TITLE = ("Event Special Rewards", (0.08, 0.0, 0.30, 0.09))
# The dialog a tap on the park's Rules of Good Order raises, a timed game Daily never plays: its line at (0.502, 0.423)
# and its 取消 at (0.347, 0.631), with 确认 at (0.667, 0.631).
RULES_LINE = ("This event takes place after reaching the highest Rank", (0.25, 0.38, 0.75, 0.48))
RULES_BUTTONS = (("取消", (0.28, 0.60, 0.42, 0.66)), ("Cancel", (0.28, 0.60, 0.42, 0.66)))
# The Profit Report the park opens on after time away, its caption where the Rank result draws its own: title at
# (0.500-0.501, 0.356) and caption at (0.499-0.500, 0.938). Under it the park's Operate does not read.
PROFIT_TITLE = ("Profit Report", (0.40, 0.32, 0.60, 0.40))
PROFIT_CAPTION = ("点击屏幕关闭窗口", (0.40, 0.90, 0.60, 0.97))
BANNER_CORNER = (0.90, 0.0, 1.0, 0.12)
BANNER_MATCH = 0.92

# The open menu's Activity, at (0.790, 0.232). The Activity window is told by its tab's title at (0.17-0.21, 0.112), which
# OCR reads with a stray `I` or `|` in front at times. The Achievement screen's `Journey Log` tab label reads at
# (0.09-0.11, 0.138), inside that band, and never holds a title. The order is the order the tabs are visited in.
MENU_ACTIVITY = ("Activity", (0.75, 0.21, 0.83, 0.26))
ACTIVITY_TITLE_REGION = (0.10, 0.08, 0.40, 0.14)
GUIDE, SCHEDULE, WEEKLY, LOG = "Growth Guide", "Achievement schedule", "Weekly Schedule", "Achievement Log"
ACTIVITY_TABS = {GUIDE: GUIDE_TAB, SCHEDULE: SCHEDULE_TAB, WEEKLY: WEEKLY_TAB, LOG: LOG_TAB}
ACTIVITY_PHASES = tuple(ACTIVITY_TABS)
# The ready faces' colours, in OpenCV's HSV: orange on the Activity window, blue on the Achievement screen. A greyed
# button or ring has none of either.
ORANGE_LOW, ORANGE_HIGH = np.array((5, 120, 150)), np.array((25, 255, 255))
BLUE_LOW, BLUE_HIGH = np.array((100, 120, 150)), np.array((125, 255, 255))
FACE_SHARE = 0.5
# Growth Guide: ready cards read `Claim Reward` at y 0.854, x 0.391, 0.584 and 0.780, and sort first; a fourth card is
# cut at the right edge (`Clai` at 0.934), outside the band. Unfinished cards read `Move`, which leaves the window. Once
# every card is claimed the stage ring at (0.873, 0.247) turns orange: 0.25-0.31 of its patch, against 0.0 otherwise.
GUIDE_CLAIMS = ("Claim Reward", (0.30, 0.82, 0.86, 0.89))
STAGE_RING = (0.858, 0.225, 0.888, 0.270)
STAGE_SHARE = 0.15
# Daily schedule: Claim All at (0.226, 0.838), its face orange (0.87) while a reached tier waits and a flat grey after.
SCHEDULE_BUTTON_REGION = (0.12, 0.80, 0.30, 0.87)
SCHEDULE_FACE = (0.12, 0.81, 0.27, 0.87)
# Weekly schedule: a finished goal's button reads `Goal Achieved` at y 0.869, its face orange (0.75-0.77) around the
# caption; `Mission Records Shop` at (0.188, 0.844) lies left of the band. A goal opens no Items Obtained: its card leaves
# the row and the progress at (0.176, 0.560), `220/1000`, rises by 100. A reached, unclaimed milestone draws its label
# (100, 200, 400, 600) orange, 0.13 of the label's patch against 0.0 claimed or unreached, and one press on its icon above
# took every reached tier.
GOAL_REGION = (0.30, 0.84, 0.86, 0.90)
GOAL_FACE_HALF = (0.055, 0.02)
WEEKLY_PROGRESS_REGION = (0.12, 0.54, 0.24, 0.58)
WEEKLY_PROGRESS = re.compile(r"(\d+)/\d+")
MILESTONES = (((0.405, 0.22), (0.385, 0.290, 0.430, 0.320)), ((0.545, 0.22), (0.525, 0.290, 0.570, 0.320)),
              ((0.685, 0.22), (0.665, 0.290, 0.710, 0.320)), ((0.825, 0.22), (0.805, 0.290, 0.850, 0.320)))
MILESTONE_SHARE = 0.05
# Achievement Log: reached, unclaimed levels sort first, and the top row's claim at (0.800, 0.290) is then orange
# (0.17-0.32); claimed or unreached it shows a grey waveform (0.0). One press takes every reached level.
LOG_RING = (0.785, 0.265, 0.815, 0.315)
LOG_SHARE = 0.1
# What a claim press must never land on, besides what `press` refuses: the `Move` that leaves the window for a mission,
# and on the Carnival `Check-In Make-Up`, which sells missed days, and Exchange's `Go`, which opens the shop.
NEVER_CLAIM = ("move", "go")
NEVER_CLAIM_PARTS = ("makeup",)
# The Achievement screen: its title at (0.143, 0.045). It opens on four category cards, `Journey Log` captioned at
# (0.141, 0.689); inside a category the same name labels the first left tab at (0.105, 0.138), and the open category's
# name heads the list at (0.376-0.428, 0.131), read as `Exploratin Atitude` at times, so each is told by its start.
# Claim All at (0.910, 0.163) has a blue face (0.81) while anything in that category is ready and a flat grey after.
ACHIEVEMENT_TITLE = ("Achievement", (0.08, 0.02, 0.22, 0.08))
CARDS_JOURNEY = ("Journey Log", (0.08, 0.66, 0.20, 0.72))
CATEGORY_JOURNEY_TAB = ("Journey Log", (0.04, 0.11, 0.18, 0.17))
CATEGORY_HEADER_REGION = (0.25, 0.10, 0.60, 0.16)
CATEGORY_NAMES = ("journey", "explor", "traces", "overcom")
CATEGORY_BUTTON_REGION = (0.84, 0.12, 0.98, 0.20)
CATEGORY_FACE = (0.85, 0.14, 0.97, 0.19)
# Claim All as OCR reads it: `Claim AIl`, `Claim AlI` and `Claim AIll` as well.
CLAIM_ALL_TEXT = re.compile(r"clalmal{2,3}")
# How many Achievement Log levels a press took, read off the screen: every reached level's orange ring in the claim
# column, 0.00048 of a 1080p frame each, three of them at y 0.291, 0.503 and 0.653 before one press took all three,
# against none after.
LOG_COLUMN = (0.77, 0.22, 0.83, 0.97)
LOG_RING_AREA = 0.00025

# The Lobby's Nightmare Carnival banner, read at (0.101, 0.396) while the event runs. Another banner in its place reads
# otherwise, so the chore is skipped rather than its spot tapped. The Carnival window: its title at (0.169, 0.047), the
# `Attendance Check` tab label at (0.109, 0.369), which takes a tap only on its left part, and the open tab's heading,
# `Attendance` at (0.795, 0.165); Exchange and Welcome Gift head their tabs at (0.906, 0.169) and (0.880, 0.164).
LOBBY_CARNIVAL = ("Nightmare Carnival", (0.02, 0.36, 0.20, 0.43))
CARNIVAL_TITLE = ("Nightmare Carnival", (0.08, 0.02, 0.30, 0.08))
CARNIVAL_ATTENDANCE_TAB = ("Attendance Check", (0.04, 0.33, 0.18, 0.41))
CARNIVAL_HEADING = ("Attendance", (0.70, 0.13, 0.88, 0.20))
# How long a Carnival window with only its title or only its tab label reading, as under a popup or after one OCR miss,
# is given before the chore is left by the back arrow: the settle time plus a navigation wait.
CARNIVAL_UNREAD_WAIT = 5
# A pending day's bar under its card, y 0.872-0.915, is filled violet (HSV 133, 148, 215) round a white download icon;
# a claimed or unreached day's bar is dark (value 72-103). Columns of violet or white, at least half the strip, make a
# bar; a run of them 0.06 wide and mostly violet is a pending day, 0.107 wide on the capture. A card cut at the list's
# left edge shows 0.013 of its bar and is left. `Check-In Make-Up` at (0.811, 0.398) and Exchange's `Go` lie outside it.
CARNIVAL_BARS = (0.22, 0.875, 0.99, 0.912)
CARNIVAL_DAY_Y = 0.885
BAR_LOW, BAR_HIGH = np.array((120, 90, 170)), np.array((145, 220, 255))
BAR_WHITE_LOW, BAR_WHITE_HIGH = np.array((0, 0, 200)), np.array((180, 70, 255))
BAR_COLUMN_SHARE = 0.5
BAR_VIOLET_SHARE = 0.5
BAR_WIDTH = 0.06

# The Event list's The Path of a Captain, read cut as `le Path of a Captain` or joined as `The Path of aCaptain`. Its
# page: the title at (0.823, 0.166) and one button per Captain level tier at y 0.914, `Claim Reward` under a reached,
# unclaimed tier, `Claimed` or `Insufficient level` under the others.
CAPTAIN_ENTRY_TEXT = "pathofacaptain"
CAPTAIN_TITLE = ("The Path of a Captain", (0.70, 0.13, 0.95, 0.20))
CAPTAIN_CLAIMS = ("Claim Reward", (0.25, 0.89, 0.99, 0.94))

# How long the screen may stay one Daily does not know before it stops, and how long a Lobby read stays good for a
# Lobby whose UI has faded out after a few idle seconds, which OCR reads as nothing but the odd low-confidence scrap:
# `rort` at 0.585 off the art on one capture, against 0.8 and up for every caption Daily reads.
UNKNOWN_SECONDS = 30
FADED_SECONDS = 20
FADED_CONFIDENCE = 0.7
# Right of this the Lobby writes its captions, Story to Combatants, and the right of its top bar. A faded Lobby reads at
# most its character's speech bubble, read at (0.258, 0.278).
CAPTION_SIDE = 0.70
# The faded Lobby without a Lobby read, as at a start on an idle Lobby, is told by its scene: the ring's left arm, cut
# from a 1080p capture, which the Lobby's level and name cover while its UI shows. It scored 0.94 to 0.96 on four
# other faded Lobby captures, the character standing or gone, and 0.46 at most over 651 other captures, black, loading,
# cut-scenes and the Lobby with its UI among them. The wake taps open sky, which brings the UI back.
FADED_SCENE_IMAGE = Path(__file__).with_name("images") / "lobby_faded_scene.png"
FADED_SCENE_REGION = (0.0, 0.02, 0.23, 0.28)
FADED_SCENE_MATCH = 0.8
# How long the UI gets to come back after the wake tap before it is tapped again.
WAKE_WAIT = 3
# How long Claim All gets to open Items Obtained before it is pressed again, or taken as having had nothing to claim.
CLAIM_WAIT = 5
# The run's chores before the park, then the park visit, then the invest step, each get their own time.
RUN_SECONDS = 600
PARK_SECONDS = 600
INVEST_SECONDS = 600
# The invest step: how long a spend panel must read unchanged before its button is pressed, since a tap in its first
# moments has been ignored; how long a press that opens a panel or a node gets to show it before the unit is skipped; how
# long a spend gets to show its result card or change its panel; and how long Auto Register gets to fill the slots.
PANEL_SETTLE = 3
PANEL_WAIT = 10
SPEND_WAIT = 5
REGISTER_WAIT = 5
# Spends in a row that changed nothing before Daily stops.
NO_EFFECT_STOP = 2
# The goal list and the Units to keep, Daily's two settings.
GOALS_SETTING = "Goal Combatants"
FLOOR_SETTING = "Units to Keep"
UNITS_FLOOR = 300_000
# How long a park screen gets to change after a press before the same target is pressed again: a second Operate or
# Manage on the open panel would close it. How long a screen gets to draw before what it lacks counts, how long a ride's
# level gets to rise after its press, and how long Rank Up gets to show its result.
NAV_WAIT = 3
SETTLE = 2
UPGRADE_WAIT = 2
# How often a pressed ride's level is read while its press waits, and where it reads: `Lv.N/50` sits 0.106-0.108 above
# the button at x 0.93, with the rate line 0.055 above the button and the row above's price 0.18 above it, both outside.
LEVEL_POLL = 0.15
LEVEL_ZONE = (0.86, 0.135, 0.08)
RANK_WAIT = 5
# Why the Skill tab was left when a skill stopped taking presses, which the finish line names.
NO_SKILL_RISE = "AI Automation's level did not rise after two presses"
NO_HAPPY_DAY_RISE = "Another Happy Day's level did not rise after two presses"

# Parked on the task for one run: dropped by `disable`, so every start begins afresh.
RUN = "_en_daily_run"

PENDING, DONE = "pending", "done"
Step = namedtuple("Step", "name lobby_entry menu_entry")
# One entry per chore, in the order they run. Each starts from the Lobby with its entry tap and ends back on the Lobby.
# The Carnival opens from the Lobby's banner, not the menu, so it comes after the menu's chores.
# The invest step comes last, so a stop on one of its screens costs none of the chores before it.
STEPS = (Step("mail", MENU, ENVELOPE), Step("activity", MENU, ACTIVITY), Step("achievement", MENU, ACHIEVEMENT_ENTRY),
         Step("carnival", CARNIVAL_BANNER, None), Step("dream_park", MENU, EVENT), Step("invest", INVEST_ENTRY, None))
# The claims whose count is read off the screen after Items Obtained closes, as what left it, rather than one per press.
RECOUNTED = ("milestone", "log", "carnival", "captain")
PARK = "dream_park"
INVEST = "invest"
# The menu captions pressed by the box OCR read, for the chores whose menu entry is a text button.
MENU_ENTRIES = {ACTIVITY: MENU_ACTIVITY, ACHIEVEMENT_ENTRY: MENU_ACHIEVEMENT}
# Where the park visit stands: reading the Manage panel, upgrading in Facilities, or on its way out to the achievements.
TO_MANAGE, TO_OPERATE, TO_LEAVE = "manage", "operate", "leave"
# The targets that lead into each park screen, which count afresh once it shows. None is pressed on the screen it leads to.
ARRIVALS = {
    "event list": (MENU, EVENT),
    "event page": (MENU, EVENT, DREAM_PARK, PARK_LEAVE, ACHIEVEMENTS_LEAVE),
    "profit report": (ENTER_PARK,),
    "park": (ENTER_PARK, PANEL_CLOSE, PROFIT_CLOSE, STORY_SKIP, SKIP_CONFIRM),
    "manage": (PARK_MANAGE, RANK_CLOSE),
    "facilities": (PARK_OPERATE, FACILITIES_TAB),
    "skill": (SKILL_TAB,),
    "rank": (PARK_RANK, RANK_RESULT_CLOSE),
    "rank result": (RANK_UP, STORY_SKIP, SKIP_CONFIRM),
    "achievements": (PARK_ACHIEVEMENTS, ITEMS_CLOSE),
}
# The targets that lead into each invest screen, which count afresh once it shows.
INVEST_ARRIVALS = {
    "list": (INVEST_ENTRY, DETAILS_LEAVE),
    "stats": (UNIT_CARD, STATS_TAB, PANEL_LEAVE),
    "partners": (PARTNERS_TAB, PANEL_LEAVE),
    "map": (POTENTIAL_TAB, NODE_LEAVE),
    "panel": (OPEN_PROMOTION, OPEN_LEVEL_UP, PARTNER_UPGRADE, RESULT_CLOSE),
    "node": (NODE_01_ENTRY, NODE_02_ENTRY, RESULT_CLOSE),
}
# The spends, which count afresh for each goal unit.
INVEST_SPENDS = (PROMOTE, LEVEL_UP, AUTO_REGISTER, ACTIVATE)
# The screens whose reading OCR may vary on without the screen changing: a press made on one is not repeated while it shows.
STEADY_SCREENS = ("stats", "partners", "map", "list")
# Where a goal unit's visit stands: its Promotion, its Level Up, its Partner's, its Potential nodes, then done.
TO_PROMOTE, TO_LEVEL, TO_PARTNER, TO_POTENTIAL, VISITED = "promote", "level", "partner", "potential", "visited"
# The screens inside the park, where a Rank Up can start one of the park's stories.
IN_PARK = ("profit report", "park", "manage", "facilities", "rank", "rank result")
# A press on a point the OCR read nothing at, shaped as a box for `press`.
Spot = namedtuple("Spot", "name x y width height")

_patched = False


def run_state(task):
    """Give the run's state, starting it on first use.

    Args:
        task: The Daily task.

    Returns:
        A dict: each step's state, the presses per target, when the run started, when the Lobby was last read, when an
        unknown screen, the Mail screen and the attendance popup were first seen, when Claim All, the wake, Claim Reward
        and the attendance popup's X were last pressed, what the mail step found, the park visit's own state and the Activity
        and Achievement claims' own state, and the invest step's.
    """
    state = vars(task).get(RUN)
    if state is None:
        state = {"steps": {step.name: PENDING for step in STEPS}, "taps": Counter(), "started": time.monotonic(),
                 "lobby_seen": None, "unknown_since": None, "mail_seen": None, "claim_pressed": None, "woken": None, "mail": None,
                 "attendance_seen": None, "attendance_claimed": None, "attendance_closed": None, "park": new_park(), "claims": new_claims(),
                 "invest": new_invest()}
        setattr(task, RUN, state)
    return state


def new_park():
    """Start the park visit's state.

    Returns:
        A dict: when the visit started, where it stands, the screen it is on and since when, when each target was last
        pressed, the last emotions read off the Manage panel and how many upgrades had been pressed then, what one
        offline stretch earns, the Rank target whose Rank Up was found grey or could not be checked, the target the
        Operate header sent the visit to the Manage panel for, every one it has sent it there for and those the panel
        then read below, the targets whose Rank Up was taken, when Rank Up was pressed, the press whose level rise is
        awaited and what it was, presses without a rise per ride, how many times the Facilities list was dragged, when
        last and the ride names it showed before that drag, whether the achievements were visited, when a claim ring was
        pressed and how many claims in a row opened nothing, the counts for the finish line and why the upgrades ended.
        Then the Profit Status rate, whether the Skill tab trip is done, the skill press whose level rise is awaited,
        presses without a rise, AI Automation presses made, the levels bought and why the trip ended; Another Happy
        Day's presses and levels, the Happiness it was short when first weighed, how many drags down the Skill tab
        the trip made, when last and the names before that drag; and the drags of the Facilities list's current opening.
    """
    return {"started": None, "phase": TO_MANAGE, "screen": None, "screen_since": None, "pressed": {}, "emotions": None, "emotions_at": 0,
            "stretch": None, "rate": None, "skill_done": False, "skill_pending": None, "skill_no_rise": 0, "skill_presses": 0,
            "skill_levels": [], "skill_note": None, "happy_presses": 0, "happy_levels": [], "happy_need": None,
            "skill_scrolls": 0, "skill_scrolled": None, "skill_scroll_names": None,
            "rank_checked": None, "rank_wanted": None, "rank_sent": set(), "rank_unmet": set(),
            "ranked": set(), "rank_pressed": None, "pending": None, "no_rise": Counter(),
            "scrolls": 0, "opening_scrolls": 0, "scrolled": None, "scroll_names": None,
            "claims_done": False, "claim_pressed": None, "claim_misses": 0, "ranks": [], "rank_ups": 0,
            "upgrades": 0, "builds": [], "claims": 0, "note": None, "result": None}


def new_claims():
    """Start the Activity and Achievement claims' state.

    Returns:
        A dict: the claim screen showing and since when, when each of their targets was last pressed, the Activity tab
        and the achievement category being worked through, the claim press awaiting its outcome, the claim awaiting its
        count once its screen settles, how many claims in a row opened nothing, the claims counted for the finish line,
        and what the Carnival and The Path of a Captain came to.
    """
    return {"screen": None, "since": None, "pressed": {}, "phase": 0, "category": 0, "pending": None, "recount": None, "misses": 0,
            "claimed": Counter(), "carnival": None, "captain": None}


def new_invest():
    """Start the invest step's state.

    Returns:
        A dict: when the step started, the goal units and the Units to keep once read, which goal unit is next and the
        visit under way, the units holding the shared materials back, the goal file's lines by unit and action, the spends
        made, the notes for the finish line, spends in a row that changed nothing, the screen showing and since when, the
        screen the last corner or node press was made on, the spend awaiting its effect, when and on what screen each
        target was last pressed, whether every goal unit has been visited, and why the goal file could not be written.
    """
    return {"started": None, "goals": None, "floor": None, "index": 0, "visit": None, "held": set(), "lines": {}, "spends": [],
            "notes": [], "misses": 0, "screen": None, "since": None, "guard": None, "spend": None, "pressed": {}, "ended": False,
            "unwritten": None}


def pending_step(task):
    """Find the first chore not yet done.

    Args:
        task: The Daily task.

    Returns:
        The step, or None when every chore is done.
    """
    steps = run_state(task)["steps"]
    return next((step for step in STEPS if steps[step.name] == PENDING), None)


def recognised(task):
    """Note that Daily knows this screen, which restarts the unknown-screen clock.

    Args:
        task: The Daily task.
    """
    run_state(task)["unknown_since"] = None


def refused(text):
    """Say whether a box reads as something Daily must never press.

    Args:
        text: The box's text.

    Returns:
        What gave it away, or None.
    """
    texts = [folded(text)]
    for group in REFUSED_GROUPS:
        marker = marker_in(texts, group)
        if marker:
            return marker
    if any(word in texts[0] for word in SHOP):
        return text
    if any(phrase.search(text.casefold()) for phrase in RESCUE_PHRASES) or cleaned(text) in RESCUE_HEADER:
        return text
    return None


def boxes_at(task, point):
    """Find the OCR boxes a tap at a point would land on.

    Args:
        task: The Daily task.
        point: `(x, y)` screen fractions.

    Returns:
        The boxes containing the point.
    """
    x, y = point[0] * task.width, point[1] * task.height
    return [box for box in getattr(task, "all_texts", None) or [] if box.x <= x <= box.x + box.width and box.y <= y <= box.y + box.height]


def level_zone(button_y):
    """Give where a ride's level reads, from its Upgrade button's height.

    Args:
        button_y: The button's centre down the screen, as a fraction.

    Returns:
        The zone as `(left, top, right, bottom)` screen fractions.
    """
    left, above, below = LEVEL_ZONE
    return left, button_y - above, 1.0, button_y - below


def tap_upgrade(task, point, level):
    """Press a ride's Upgrade, then wait until its level reads risen, never longer than any other press waits.

    Only the row's own level is read, a small zone, so a look costs far less than a pass. What it reads never presses:
    the next pass reads the whole list and `ride_risen` decides as before. Without a rise the wait is `AFTER_TAP`, as for
    any other press.

    Args:
        task: The Daily task, whose sleep drops the frame so each look reads a new one.
        point: The button's centre as `(x, y)` screen fractions.
        level: The ride's level before the press.
    """
    tap(task, point, 0)
    deadline = time.monotonic() + AFTER_TAP
    for _ in range(math.ceil(AFTER_TAP / LEVEL_POLL)):
        # A look starts only while it and the sleep before it fit in what is left: a zone read took 13-48ms offline.
        if deadline - time.monotonic() < 2 * LEVEL_POLL:
            break
        task.sleep(LEVEL_POLL)
        read = (dream_park.LEVEL.search(box.name) for box in task.ocr(*level_zone(point[1])) or [])
        if any(found and int(found.group(1)) > level for found in read):
            return
    task.sleep(max(deadline - time.monotonic(), 0))


def press(task, target, box=None, level=None):
    """Press one of Daily's targets, unless its limit is reached or what lies under it must never be pressed.

    Args:
        task: The Daily task.
        target: A key of `TARGETS`.
        box: The OCR box for a text button, None for a fixed point.
        level: For a ride's Upgrade, the ride's level before the press, which ends the wait once it reads risen.

    Returns:
        True, which claims the frame: the target was pressed, or Daily has stopped.
    """
    taps = run_state(task)["taps"]
    if taps[target] >= TAP_LIMITS[target]:
        return stop(task, f"Stopped: {target} was pressed {taps[target]} times and the screen did not move on. Check the game, then press Start again.")
    point = centre_of(box, task.width, task.height) if box is not None else TARGETS[target]
    under = [box] if box is not None else []
    for hit in under + boxes_at(task, point):
        marker = refused(hit.name)
        if marker:
            task.log_info(f"not pressing {target}: the box there reads {hit.name!r} ({marker!r})")
            return stop(task, f"Stopped: {target} would have pressed {hit.name!r}. Check the game, then press Start again.")
    taps[target] += 1
    task.log_info(f"pressing {target}")
    if target == UPGRADE and level is not None:
        tap_upgrade(task, point, level)
    else:
        tap(task, point)
    return True


def showing(task, caption):
    """Find a caption in its region.

    Args:
        task: The Daily task.
        caption: A `(text, region)` pair from the constants above.

    Returns:
        The box, or None.
    """
    return text_in_region(task, *caption)


def on_lobby(task):
    """Say whether the screen is the Lobby with its menu closed."""
    return showing(task, LOBBY_STORY) is not None and showing(task, LOBBY_COMBATANTS) is not None


def on_menu(task):
    """Say whether the Lobby's menu is open."""
    return showing(task, MENU_ACHIEVEMENT) is not None and showing(task, MENU_SUPPLY) is not None


def on_notice(task):
    """Say whether the Notice board is open."""
    return showing(task, NOTICE_TAB) is not None and showing(task, UPDATE_TAB) is not None


def on_mail(task):
    """Say whether the Mail screen is open."""
    if showing(task, MAIL_TITLE) is None:
        return False
    return any(MAIL_COUNT.fullmatch(folded(box.name)) and in_region(box, MAIL_COUNT_REGION, task.width, task.height)
               for box in getattr(task, "all_texts", None) or [])


def claim_all_button(task):
    """Find Claim All on the Mail screen.

    OCR has read it as `Claim AIl` and `Claim AlI`, so capital I and small l count as one letter.

    Args:
        task: The Daily task.

    Returns:
        The box, or None.
    """
    wanted = folded(CLAIM_ALL).replace("i", "l")
    for box in getattr(task, "all_texts", None) or []:
        if folded(box.name).replace("i", "l") == wanted and in_region(box, CLAIM_ALL_REGION, task.width, task.height):
            return box
    return None


def claim_all_greyed(task):
    """Say whether Claim All is drawn greyed out, with nothing left to claim.

    Args:
        task: The Daily task.

    Returns:
        True when its face is grey. False when it is orange, or there is no frame to read.
    """
    return colour_share(patch_of(frame_of(task), CLAIM_ALL_FACE), GREYED_LOW, GREYED_HIGH) >= GREYED_SHARE


def reads_as_faded_lobby(task):
    """Say whether OCR read no more than a Lobby whose UI has faded out shows.

    That is no Lobby caption, and at most one confident line, the character's speech bubble, left of where the Lobby
    writes its captions. The scene still has to tell the faded Lobby from any other screen reading as little.
    """
    if showing(task, LOBBY_STORY) is not None:
        return False
    confident = [box for box in getattr(task, "all_texts", None) or [] if box.name.strip() and getattr(box, "confidence", 1.0) >= FADED_CONFIDENCE]
    return len(confident) <= 1 and all(centre_of(box, task.width, task.height)[0] < CAPTION_SIDE for box in confident)


def handle_daily_tutorial(task):
    """Stop while the tutorial's Skip Tutorial pill shows, ahead of every handler that presses.

    OCR read the pill, white on black, on every capture that shows it, so this is Daily's own stop for it. A frame where
    OCR misses the pill falls to the handlers below, and a press of the Lobby's Menu, the banner's X or the menu's X
    there is left to the guard in `skip_tutorial`, which refuses any tap on the pill in every mode.
    """
    if showing(task, SKIP_TUTORIAL) is None:
        return False
    return stop(task, "Stopped: the tutorial is running (Skip Tutorial shows), and Daily never skips it. Finish the tutorial, then press Start again.")


def handle_daily_overtime(task):
    """Stop a run that has gone on far longer than its chores take, the park visit and the invest step each timed on their own while under way."""
    state = run_state(task)
    now = time.monotonic()
    step = pending_step(task)
    if step is None:
        return False
    if step.name in (PARK, INVEST):
        clock, seconds, what = (state["park"], PARK_SECONDS, "the Dream Park visit") if step.name == PARK else (state["invest"], INVEST_SECONDS, "the invest step")
        if clock["started"] is None:
            clock["started"] = now
        if now - clock["started"] < seconds:
            return False
        return stop(task, f"Stopped: {what} ran for {seconds // 60} minutes without finishing. Check the game, then press Start again.")
    if now - state["started"] < RUN_SECONDS:
        return False
    return stop(task, f"Stopped: Daily ran for {RUN_SECONDS // 60} minutes without finishing. Check the game, then press Start again.")


def handle_daily_items_obtained(task):
    """Close Items Obtained, counting what opened it: the mail's Claim All, a park achievement's ring, or an Activity or Achievement claim."""
    if showing(task, ITEMS_TITLE) is None:
        return False
    caption = showing(task, ITEMS_CAPTION)
    if caption is None:
        return False
    recognised(task)
    state = run_state(task)
    if state["claim_pressed"] is not None and state["steps"]["mail"] == PENDING:
        state["steps"]["mail"], state["mail"] = DONE, "claimed"
    park = state["park"]
    if park["claim_pressed"] is not None:
        park["claim_pressed"], park["claim_misses"] = None, 0
        park["claims"] += 1
    claims = state["claims"]
    if claims["pending"] is not None:
        kind, _, before = claims["pending"]
        if kind in RECOUNTED:
            claims["recount"] = (kind, before)
        else:
            claims["claimed"][kind] += 1
        claims["pending"], claims["misses"] = None, 0
        # The screen under it redraws its cards, so it gets time to settle again before it is read.
        claims["screen"] = None
    return press(task, ITEMS_CLOSE, caption)


def handle_daily_attendance(task):
    """Claim today's card on the daily attendance popup, then close the popup on its X.

    Claim Reward opens Items Obtained, which `handle_daily_items_obtained` closes, and the stamped popup under it shows no
    Claim Reward. A popup without one is given a moment to draw before it counts as claimed, and a claim that opened
    nothing is retried once, then the popup is closed all the same. Items Obtained's caption counts afresh while the
    popup shows, as a screen's arrival does, so the claim's Items Obtained and the mail's each get the caption's limit.
    """
    if showing(task, ATTENDANCE_TITLE) is None or showing(task, ATTENDANCE_TAG) is None:
        return False
    recognised(task)
    state = run_state(task)
    state["taps"][ITEMS_CLOSE] = 0
    now = time.monotonic()
    if state["attendance_seen"] is None:
        state["attendance_seen"] = now
    claimed = state["attendance_claimed"]
    if claimed is not None and now - claimed < CLAIM_WAIT:
        return True
    claim = showing(task, ATTENDANCE_CARDS)
    if claim is not None and state["taps"][ATTENDANCE_CLAIM] < TAP_LIMITS[ATTENDANCE_CLAIM]:
        state["attendance_claimed"] = now
        return press(task, ATTENDANCE_CLAIM, claim)
    closed = state["attendance_closed"]
    if now - state["attendance_seen"] < SETTLE or (closed is not None and now - closed < NAV_WAIT):
        return True
    state["attendance_closed"] = now
    return press(task, ATTENDANCE_CLOSE)


def nothing_to_claim(task, reason):
    """Count the mail as done with nothing claimed, and close the Mail popup.

    Args:
        task: The Daily task.
        reason: Why, for the log.

    Returns:
        True, which claims the frame.
    """
    task.log_info(f"{reason}, so there is no mail to claim")
    state = run_state(task)
    state["steps"]["mail"], state["mail"] = DONE, "nothing to claim"
    return press(task, MAIL_CLOSE)


def handle_daily_mail(task):
    """Press Claim All while the mail is pending, wait for Items Obtained, and close the popup once it is done.

    A greyed Claim All is waited on like a missing one, since the popup may still be drawing, then taken as an empty mailbox.
    """
    if not on_mail(task):
        return False
    recognised(task)
    state = run_state(task)
    now = time.monotonic()
    for target in TOWARD_MAIL:
        state["taps"][target] = 0
    if state["mail_seen"] is None:
        state["mail_seen"] = now
    if state["steps"]["mail"] != PENDING:
        return press(task, MAIL_CLOSE)
    if showing(task, MAIL_EMPTY) is not None:
        return nothing_to_claim(task, "the game says every mail has been received")
    pressed = state["claim_pressed"]
    if pressed is not None and now - pressed < CLAIM_WAIT:
        return True
    if state["taps"][CLAIM_ALL] >= TAP_LIMITS[CLAIM_ALL]:
        return nothing_to_claim(task, "Claim All opened nothing")
    button = claim_all_button(task)
    greyed = button is not None and claim_all_greyed(task)
    if (button is None or greyed) and now - state["mail_seen"] < CLAIM_WAIT:
        return True
    if greyed:
        return nothing_to_claim(task, "Claim All is greyed out")
    if button is None:
        return nothing_to_claim(task, "no Claim All on the Mail screen")
    state["claim_pressed"] = now
    return press(task, CLAIM_ALL, button)


def claim_step_active(task, name):
    """Say whether the named claim chore, `activity` or `achievement`, is the one under way."""
    step = pending_step(task)
    return step is not None and step.name == name


def claims_state(task):
    """Give the Activity and Achievement claims' state."""
    return run_state(task)["claims"]


def arrive_claim_screen(task, screen, entries):
    """Note that a claim screen shows: restart the unknown-screen clock and count afresh the targets that lead to it.

    Items Obtained's caption counts afresh too, as under the attendance popup, since every claim here opens it and its
    run limit would otherwise stop Daily at the third claim.

    Args:
        task: The Daily task.
        screen: What shows, for how long it has shown.
        entries: The targets that lead to this screen.

    Returns:
        How long, in seconds, this screen has shown without another claim screen or Items Obtained in between.
    """
    recognised(task)
    taps = run_state(task)["taps"]
    for target in (ITEMS_CLOSE, *entries):
        taps[target] = 0
    claims = claims_state(task)
    now = time.monotonic()
    if claims["screen"] != screen:
        claims["screen"], claims["since"] = screen, now
    return now - claims["since"]


def press_settled(task, target, box=None):
    """Press a claim screen's tab, card or exit, unless it was pressed moments ago and the screen may still be changing.

    Args:
        task: The Daily task.
        target: A key of `TARGETS`.
        box: The OCR box for a text button, None for a fixed point.

    Returns:
        True, which claims the frame.
    """
    pressed = claims_state(task)["pressed"]
    now = time.monotonic()
    if target in pressed and now - pressed[target] < NAV_WAIT:
        return True
    pressed[target] = now
    return press(task, target, box)


def face_share(task, region, low, high):
    """Say how much of a region of the frame is drawn in one band of colour, 0 when there is no frame."""
    return colour_share(patch_of(frame_of(task), region), low, high)


def captions_in(task, caption):
    """Find every box of a caption in its region, left to right.

    Args:
        task: The Daily task.
        caption: A `(text, region)` pair.

    Returns:
        The boxes.
    """
    wanted, region = folded(caption[0]), caption[1]
    boxes = (box for box in getattr(task, "all_texts", None) or [] if wanted in folded(box.name) and in_region(box, region, task.width, task.height))
    return sorted(boxes, key=lambda box: box.x)


def claim_all_in(task, region):
    """Find a Claim All button in a region, however OCR mixed up its capital I and small l.

    Args:
        task: The Daily task.
        region: A `(left, top, right, bottom)` tuple in screen fractions.

    Returns:
        The box, or None.
    """
    return next((box for box in getattr(task, "all_texts", None) or []
                 if CLAIM_ALL_TEXT.fullmatch(folded(box.name).replace("i", "l")) and in_region(box, region, task.width, task.height)), None)


def weekly_progress(task):
    """Read the weekly schedule's progress points, or None when they do not read."""
    for box in getattr(task, "all_texts", None) or []:
        found = WEEKLY_PROGRESS.fullmatch(folded(box.name))
        if found and in_region(box, WEEKLY_PROGRESS_REGION, task.width, task.height):
            return int(found.group(1))
    return None


def goal_lit(task, box):
    """Say whether a `Goal Achieved` button is drawn orange around its caption."""
    x, y = centre_of(box, task.width, task.height)
    half_x, half_y = GOAL_FACE_HALF
    return face_share(task, (x - half_x, y - half_y, x + half_x, y + half_y), ORANGE_LOW, ORANGE_HIGH) >= FACE_SHARE


def ready_activity_claim(task, tab):
    """Find the next ready claim on an Activity tab.

    Args:
        task: The Daily task.
        tab: The tab's title, a key of `ACTIVITY_TABS`.

    Returns:
        `(target, kind, box)` for `press_claim`, the box None for a fixed point, or None when nothing on the tab is ready.
    """
    if tab == GUIDE:
        cards = captions_in(task, GUIDE_CLAIMS)
        if cards:
            return GUIDE_CLAIM, "guide", cards[0]
        if face_share(task, STAGE_RING, ORANGE_LOW, ORANGE_HIGH) >= STAGE_SHARE:
            return STAGE_CLAIM, "stage", None
    elif tab == SCHEDULE:
        button = claim_all_in(task, SCHEDULE_BUTTON_REGION)
        if button is not None and face_share(task, SCHEDULE_FACE, ORANGE_LOW, ORANGE_HIGH) >= FACE_SHARE:
            return SCHEDULE_CLAIM, "schedule", button
    elif tab == WEEKLY:
        goal = next((box for box in captions_in(task, ("Goal Achieved", GOAL_REGION)) if goal_lit(task, box)), None)
        if goal is not None:
            return GOAL_CLAIM, "goal", goal
        for (x, y), label in MILESTONES:
            if face_share(task, label, ORANGE_LOW, ORANGE_HIGH) >= MILESTONE_SHARE:
                return MILESTONE_CLAIM, "milestone", Spot("milestone", x * task.width - 1, y * task.height - 1, 2, 2)
    elif tab == LOG:
        if face_share(task, LOG_RING, ORANGE_LOW, ORANGE_HIGH) >= LOG_SHARE:
            return LOG_CLAIM, "log", None
    return None


def never_claimed(text):
    """Say whether a box reads as something no claim press may land on: a `Move`, Make-Up or `Go`."""
    word = folded(text)
    return word in NEVER_CLAIM or any(part in word for part in NEVER_CLAIM_PARTS)


def press_claim(task, target, kind, box=None, before=None):
    """Press a ready claim and await what it opens, unless a `Move`, Make-Up or `Go` lies under it.

    Args:
        task: The Daily task.
        target: A key of `TARGETS`.
        kind: What is claimed, a key of the finish line's counts.
        box: The OCR box or spot pressed, None for the target's fixed point.
        before: For a claim in `RECOUNTED`, how many of its kind read ready when it was pressed.

    Returns:
        True, which claims the frame.
    """
    point = centre_of(box, task.width, task.height) if box is not None else TARGETS[target]
    hit = next((hit for hit in ([box] if box is not None else []) + boxes_at(task, point) if never_claimed(hit.name)), None)
    if hit is not None:
        task.log_info(f"not pressing {target}: the box there reads {hit.name!r}")
        return stop(task, f"Stopped: {target} would have pressed {hit.name!r}. Check the game, then press Start again.")
    if kind == "goal":
        before = (weekly_progress(task), goals_shown(task))
    claims_state(task)["pending"] = (kind, time.monotonic(), before)
    return press(task, target, box)


def goals_shown(task):
    """Count the weekly goals reading `Goal Achieved`."""
    return len(captions_in(task, ("Goal Achieved", GOAL_REGION)))


def goals_taken(task, before):
    """Count the weekly goals a press took: the cards that left the row, or one when only the progress rose.

    Args:
        task: The Daily task.
        before: The progress and the number of `Goal Achieved` buttons when it was pressed.

    Returns:
        How many were taken, 0 when nothing changed.
    """
    progress, goals = before
    left = goals - goals_shown(task)
    if left > 0:
        return left
    now = weekly_progress(task)
    return 1 if progress is not None and now is not None and now > progress else 0


def lit_milestones(task):
    """Count the weekly milestones reached and unclaimed, by their orange labels."""
    return sum(face_share(task, label, ORANGE_LOW, ORANGE_HIGH) >= MILESTONE_SHARE for _, label in MILESTONES)


def log_rings(task):
    """Count the Achievement Log's reached, unclaimed levels by the orange rings in its claim column, 0 without a frame."""
    hsv = hsv_of(patch_of(frame_of(task), LOG_COLUMN))
    if hsv is None:
        return 0
    lit = (cv2.inRange(hsv, ORANGE_LOW, ORANGE_HIGH) > 0).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(lit)
    least = LOG_RING_AREA * task.width * task.height
    return sum(1 for stat in stats[1:count] if stat[cv2.CC_STAT_AREA] >= least)


def pending_days(task):
    """Find the Carnival's pending attendance days by their violet bars.

    Args:
        task: The Daily task.

    Returns:
        Each pending day's bar as `(left, right)` screen fractions, left to right, empty without a frame.
    """
    patch = patch_of(frame_of(task), CARNIVAL_BARS)
    hsv = hsv_of(patch)
    if hsv is None:
        return []
    violet = cv2.inRange(hsv, BAR_LOW, BAR_HIGH) > 0
    bar = (violet | (cv2.inRange(hsv, BAR_WHITE_LOW, BAR_WHITE_HIGH) > 0)).mean(axis=0) >= BAR_COLUMN_SHARE
    left, _, right, _ = CARNIVAL_BARS
    scale = (right - left) / bar.size
    edges = np.flatnonzero(np.diff(np.concatenate(([0], bar.astype(np.int8), [0]))))
    return [(left + start * scale, left + end * scale) for start, end in zip(edges[::2], edges[1::2])
            if (end - start) * scale >= BAR_WIDTH and violet[:, start:end].mean() >= BAR_VIOLET_SHARE]


def captain_claims(task):
    """Find The Path of a Captain's ready tiers, by their `Claim Reward`, left to right."""
    return captions_in(task, CAPTAIN_CLAIMS)


# What reads, on each claim's own screen, how many of its kind are still ready.
COUNTERS = {"milestone": lit_milestones, "log": log_rings, "carnival": lambda task: len(pending_days(task)),
            "captain": lambda task: len(captain_claims(task))}


def settle_recount(task, here=()):
    """Count a claim whose Items Obtained has closed, as how many of its kind left the screen.

    At least one counts, since Items Obtained showed. Off its own screen nothing can be read, so it counts as one.

    Args:
        task: The Daily task.
        here: The kinds the screen showing can count.
    """
    claims = claims_state(task)
    if claims["recount"] is None:
        return
    kind, before = claims["recount"]
    claims["recount"] = None
    left = before - COUNTERS[kind](task) if kind in here and before is not None else 1
    claims["claimed"][kind] += max(left, 1)


def claim_outcome(task):
    """Await the last claim press's outcome, and count one that opened nothing.

    Items Obtained clears the press when it shows. A weekly goal opens none, so it counts by `goals_taken` instead.

    Args:
        task: The Daily task.

    Returns:
        True while the outcome is awaited or once Daily has stopped on a second claim in a row that opened nothing, None
        when the screen may be read.
    """
    claims = claims_state(task)
    if claims["pending"] is None:
        return None
    kind, pressed, before = claims["pending"]
    if time.monotonic() - pressed < CLAIM_WAIT:
        return True
    claims["pending"] = None
    taken = goals_taken(task, before) if kind == "goal" else 0
    if taken:
        claims["claimed"][kind] += taken
        claims["misses"] = 0
        return None
    claims["misses"] += 1
    task.log_info(f"the {kind} claim opened nothing")
    if claims["misses"] >= 2:
        return stop(task, "Stopped: two claims in a row opened nothing. Check the game, then press Start again.")
    return None


# Which recounted claims each Activity tab can count.
TAB_COUNTS = {WEEKLY: ("milestone",), LOG: ("log",)}


def activity_tab(task):
    """Give the title of the Activity tab that shows, or None when the Activity window does not."""
    return next((title for title in ACTIVITY_PHASES if text_in_region(task, title, ACTIVITY_TITLE_REGION) is not None), None)


def handle_daily_activity(task):
    """Claim what is ready on the Activity window's Growth Guide, daily schedule, weekly schedule and Achievement Log, then close it.

    The tabs are worked through in that order, each given time to draw before what it lacks counts, and a tab with
    nothing ready hands over to the next. Off the Activity step the window is only closed.
    """
    tab = activity_tab(task)
    if tab is None:
        return False
    shown_for = arrive_claim_screen(task, tab, (MENU, ACTIVITY, ACTIVITY_TABS[tab]))
    if not claim_step_active(task, "activity"):
        return press_settled(task, ACTIVITY_CLOSE)
    waiting = claim_outcome(task)
    if waiting is not None:
        return waiting
    claims = claims_state(task)
    if claims["recount"] is not None:
        if shown_for < SETTLE:
            return True
        settle_recount(task, TAB_COUNTS.get(tab, ()))
    while claims["phase"] < len(ACTIVITY_PHASES):
        wanted = ACTIVITY_PHASES[claims["phase"]]
        if tab != wanted:
            return press_settled(task, ACTIVITY_TABS[wanted])
        if shown_for < SETTLE:
            return True
        claim = ready_activity_claim(task, tab)
        if claim is not None:
            target, kind, box = claim
            return press_claim(task, target, kind, box, max(COUNTERS[kind](task), 1) if kind in RECOUNTED else None)
        claims["phase"] += 1
    run_state(task)["steps"]["activity"] = DONE
    return press_settled(task, ACTIVITY_CLOSE)


def category_shown(task):
    """Say which achievement category is open.

    Returns:
        Its index in `CATEGORY_TABS`, -1 when a category shows but its heading does not read, or None when none shows.
    """
    if showing(task, ACHIEVEMENT_TITLE) is None or showing(task, CATEGORY_JOURNEY_TAB) is None:
        return None
    for box in getattr(task, "all_texts", None) or []:
        if in_region(box, CATEGORY_HEADER_REGION, task.width, task.height):
            index = next((index for index, start in enumerate(CATEGORY_NAMES) if start in folded(box.name)), None)
            if index is not None:
                return index
    return -1


def handle_daily_achievement_category(task):
    """Press Claim All in each of the four achievement categories in turn while its face is blue, then go back."""
    index = category_shown(task)
    if index is None:
        return False
    entries = (MENU, ACHIEVEMENT_ENTRY, JOURNEY_CARD) + ((CATEGORY_TABS[index],) if index >= 0 else ())
    shown_for = arrive_claim_screen(task, ("achievement category", index), entries)
    if not claim_step_active(task, "achievement"):
        return press_settled(task, CATEGORY_LEAVE)
    waiting = claim_outcome(task)
    if waiting is not None:
        return waiting
    claims = claims_state(task)
    while claims["category"] < len(CATEGORY_TABS):
        if shown_for < SETTLE:
            return True
        if index != claims["category"]:
            return press_settled(task, CATEGORY_TABS[claims["category"]])
        button = claim_all_in(task, CATEGORY_BUTTON_REGION)
        if button is not None and face_share(task, CATEGORY_FACE, BLUE_LOW, BLUE_HIGH) >= FACE_SHARE:
            return press_claim(task, CATEGORY_CLAIM, "category", button)
        claims["category"] += 1
        run_state(task)["taps"][CATEGORY_CLAIM] = 0
    run_state(task)["steps"]["achievement"] = DONE
    return press_settled(task, CATEGORY_LEAVE)


def handle_daily_achievement_cards(task):
    """Open the first category from the Achievement screen's four cards, or go back once the achievements are done."""
    if showing(task, ACHIEVEMENT_TITLE) is None or showing(task, CARDS_JOURNEY) is None:
        return False
    arrive_claim_screen(task, "achievement cards", (MENU, ACHIEVEMENT_ENTRY))
    return press_settled(task, JOURNEY_CARD if claim_step_active(task, "achievement") else CARDS_LEAVE)


def end_carnival(task, result="visited"):
    """Count the Carnival chore as done, with what it came to for the finish line."""
    claims_state(task)["carnival"] = result
    run_state(task)["steps"]["carnival"] = DONE


def handle_daily_carnival(task):
    """Claim every pending Carnival attendance day with one press on one of them, then go back to the Lobby.

    The window is told by its title and its Attendance Check tab before anything is pressed. With only one of them
    reading, nothing but the back arrow is pressed, once the window has had time to read, and the chore ends with a
    note rather than Daily stopping. On another tab, the Attendance Check tab is pressed, twice at most, and a tab that
    will not open ends the chore. Off the chore the window is only left.
    """
    read = showing(task, CARNIVAL_TITLE) is not None, showing(task, CARNIVAL_ATTENDANCE_TAB) is not None
    if not any(read):
        return False
    heading = showing(task, CARNIVAL_HEADING) if all(read) else None
    shown_for = arrive_claim_screen(task, ("carnival", all(read), heading is not None), (CARNIVAL_BANNER, WAKE))
    if not claim_step_active(task, "carnival"):
        return press_settled(task, CARNIVAL_LEAVE)
    waiting = claim_outcome(task)
    if waiting is not None:
        return waiting
    if not all(read):
        if shown_for < CARNIVAL_UNREAD_WAIT:
            return True
        settle_recount(task)
        end_carnival(task, "Carnival: its window did not read")
        return press_settled(task, CARNIVAL_LEAVE)
    if shown_for < SETTLE:
        return True
    settle_recount(task, ("carnival",) if heading is not None else ())
    if heading is None:
        if run_state(task)["taps"][CARNIVAL_TAB] < TAP_LIMITS[CARNIVAL_TAB]:
            return press_settled(task, CARNIVAL_TAB)
        end_carnival(task, "Carnival: its Attendance Check did not open")
        return press_settled(task, CARNIVAL_LEAVE)
    days = pending_days(task)
    if days:
        x, y = (days[0][0] + days[0][1]) / 2 * task.width, CARNIVAL_DAY_Y * task.height
        return press_claim(task, CARNIVAL_DAY, "carnival", Spot("pending day", x - 1, y - 1, 2, 2), len(days))
    end_carnival(task)
    return press_settled(task, CARNIVAL_LEAVE)


def counted(number, label):
    """Put a count before a label, the label plural unless the count is one."""
    return f"{number} {label}{'s' if number != 1 else ''}"


def claims_summary(claims):
    """Say in a few words what the Activity, Achievement, Carnival and The Path of a Captain claims took, for the finish line.

    Growth Guide cards and stage rewards take one reward a press. Weekly goals, milestone tiers, Achievement Log levels,
    Carnival days and Path of a Captain tiers count what left the screen. The daily schedule's and each achievement
    category's Claim All take every ready row at once, which no screen counts, so they are told as presses.

    Args:
        claims: The claims' state.

    Returns:
        The words.
    """
    claimed = claims["claimed"]
    labels = (("guide", "Growth Guide card"), ("stage", "Growth Guide stage reward"), ("schedule", None), ("goal", "weekly goal"),
              ("milestone", "weekly milestone tier"), ("log", "Achievement Log level"))
    parts = [counted(claimed[kind], label) if label else
             f"Claim All on the daily schedule{'' if claimed[kind] == 1 else ' ' + counted(claimed[kind], 'time')}"
             for kind, label in labels if claimed[kind]]
    categories = claimed["category"]
    achievements = f"Claim All in {categories} categor{'ies' if categories != 1 else 'y'}" if categories else "nothing to claim"
    summary = f"Activity: {', '.join(parts) if parts else 'nothing to claim'}; Achievements: {achievements}"
    carnival = claims["carnival"]
    if carnival is not None:
        summary += "; " + (carnival if carnival != "visited" else
                           f"Carnival: {counted(claimed['carnival'], 'attendance day') if claimed['carnival'] else 'nothing to claim'}")
    if claims["captain"] == "visited":
        summary += f"; The Path of a Captain: {counted(claimed['captain'], 'tier') if claimed['captain'] else 'nothing to claim'}"
    return summary


def park_active(task):
    """Say whether the park visit is the chore under way."""
    step = pending_step(task)
    return step is not None and step.name == PARK


def park_state(task):
    """Give the park visit's state."""
    return run_state(task)["park"]


def arrive(task, screen):
    """Note that a park screen shows: restart the unknown-screen clock and count afresh the targets that lead to it.

    Args:
        task: The Daily task.
        screen: A key of `ARRIVALS`.

    Returns:
        How long, in seconds, this screen has shown without another park screen in between.
    """
    recognised(task)
    taps = run_state(task)["taps"]
    for target in ARRIVALS.get(screen, ()):
        taps[target] = 0
    park = park_state(task)
    now = time.monotonic()
    if park["screen"] != screen:
        park["screen"], park["screen_since"] = screen, now
    return now - park["screen_since"]


def press_once(task, target, box=None):
    """Press a park target, unless it was pressed moments ago and its screen may still be changing.

    Args:
        task: The Daily task.
        target: A key of `TARGETS`.
        box: The OCR box for a text button, None for a fixed point.

    Returns:
        True, which claims the frame.
    """
    pressed = park_state(task)["pressed"]
    now = time.monotonic()
    if target in pressed and now - pressed[target] < NAV_WAIT:
        return True
    pressed[target] = now
    return press(task, target, box)


def end_park(task, result=None):
    """Count the park visit as done, with why it ended early when it did.

    Args:
        task: The Daily task.
        result: The finish line's words for a visit that never reached the park, or None.
    """
    state = run_state(task)
    state["steps"][PARK] = DONE
    if result is not None:
        state["park"]["result"] = result


def park_summary(park):
    """Say in a few words what the park visit did, for the finish line.

    Args:
        park: The park visit's state.

    Returns:
        The words.
    """
    if park["result"] is not None:
        return park["result"]
    parts = [f"{park['upgrades']} upgrade{'s' if park['upgrades'] != 1 else ''}"]
    if park["rank_ups"]:
        parts.append(f"ranked up to Rank {park['ranks'][-1]}" if park["ranks"] else f"ranked up {park['rank_ups']} time(s)")
    if park["builds"]:
        parts.append(f"built {', '.join(park['builds'])}")
    if park["skill_levels"]:
        parts.append(f"bought AI Automation Lv.{', Lv.'.join(str(level) for level in park['skill_levels'])}")
    if park["happy_levels"]:
        parts.append(f"bought Another Happy Day Lv.{', Lv.'.join(str(level) for level in park['happy_levels'])}")
    parts.append(f"{park['claims']} achievement claim{'s' if park['claims'] != 1 else ''}")
    summary = "Dream Park: " + ", ".join(parts)
    summary += f" (upgrades ended: {park['note']})" if park["note"] else ""
    return summary + (f" ({park['skill_note']})" if park["skill_note"] in (NO_SKILL_RISE, NO_HAPPY_DAY_RISE) else "")


def handle_daily_rules_dialog(task):
    """Decline the Rules of Good Order, a timed game Daily never plays, with its 取消 and never its 确认."""
    if showing(task, RULES_LINE) is None:
        return False
    button = next((box for box in (showing(task, caption) for caption in RULES_BUTTONS) if box is not None), None)
    if button is None:
        return False
    recognised(task)
    return press_once(task, RULES_CANCEL, button)


def handle_daily_profit_report(task):
    """Close the Profit Report the park opens on after time away, on its caption."""
    if showing(task, PROFIT_TITLE) is None:
        return False
    caption = showing(task, PROFIT_CAPTION)
    if caption is None:
        return False
    arrive(task, "profit report")
    return press_once(task, PROFIT_CLOSE, caption)


def in_park(task):
    """Say whether the park visit is under way and has reached a screen inside the park."""
    return park_active(task) and park_state(task)["screen"] in IN_PARK


def handle_daily_skip_dialog(task):
    """Tick "Do not show until next login" on a park story's skip dialog, once a run, then press its 确认.

    A box that did not take is left unticked and the story skipped all the same.
    """
    if not shown(task, COMPACT_SKIP_DIALOG) or not in_park(task):
        return False
    recognised(task)
    if box_state(frame_of(task), TARGETS[SKIP_TICK]) == UNTICKED:
        ticked = park_state(task)["pressed"].get(SKIP_TICK)
        if ticked is None:
            return press_once(task, SKIP_TICK)
        if time.monotonic() - ticked < NAV_WAIT:
            return True
    confirm = next(box for box in getattr(task, "all_texts", None) or []
                   if cleaned(box.name) == "确认" and in_region(box, COMPACT_SKIP_DIALOG.buttons_region, task.width, task.height))
    return press_once(task, SKIP_CONFIRM, confirm)


def handle_daily_park_story(task):
    """Press Skip on the dialogue bar of a story the park plays, as the Rank 8 Rank Up does before its result."""
    if not in_park(task):
        return False
    point = find_icon(frame_of(task), SKIP_IMAGE, SKIP_MATCH)
    if point is None:
        return False
    recognised(task)
    x, y = point[0] * task.width, point[1] * task.height
    return press_once(task, STORY_SKIP, Spot("Skip", x - 1, y - 1, 2, 2))


def handle_daily_rank_result(task):
    """Close the Rank result, counting the rank up."""
    if not any(RANK_ACHIEVED.search(box.name) and in_region(box, RANK_ACHIEVED_REGION, task.width, task.height)
               for box in getattr(task, "all_texts", None) or []):
        return False
    caption = showing(task, RANK_CAPTION)
    if caption is None:
        return False
    arrive(task, "rank result")
    park = park_state(task)
    if park["rank_pressed"] is not None:
        park["rank_ups"] += 1
        park["rank_pressed"] = None
        if park["emotions"] is not None:
            park["ranked"].add(park["emotions"][1])
    return press_once(task, RANK_RESULT_CLOSE, caption)


def handle_daily_rank_screen(task):
    """Press Rank Up only on the blue pill of an earned Rank, else close the screen.

    The caption is drawn on the next Rank's card whether or not it is earned, and stays on the next, grey card after a rank
    up, so the caption alone would press it again and again.
    """
    if showing(task, RANK_TITLE) is None:
        return False
    arrive(task, "rank")
    park = park_state(task)
    now = time.monotonic()
    pressed = park["rank_pressed"]
    if pressed is not None and now - pressed < RANK_WAIT:
        return True
    button = dream_park.rank_up_button(task)
    if park_active(task) and button is not None and dream_park.rank_up_live(frame_of(task), button, task.width, task.height):
        park["rank_pressed"] = now
        return press(task, RANK_UP, button)
    if park["emotions"] is not None:
        park["rank_checked"] = park["emotions"][1]
    return press_once(task, RANK_CLOSE)


def handle_daily_manage_panel(task):
    """Read the emotions, the profit rate and the idle time, then open the Rank when every emotion has reached its target."""
    if showing(task, MANAGE_EMOTIONS) is None or showing(task, MANAGE_RANK) is None:
        return False
    shown_for = arrive(task, "manage")
    park = park_state(task)
    if not park_active(task) or park["phase"] == TO_LEAVE:
        return press_once(task, PANEL_CLOSE)
    emotions = dream_park.manage_emotions(task, park["rank_wanted"])
    if emotions is None and shown_for < SETTLE:
        return True
    rank = next((RANK_NUMBER.search(box.name) for box in getattr(task, "all_texts", None) or []
                 if in_region(box, MANAGE_TITLE_REGION, task.width, task.height) and RANK_NUMBER.search(box.name)), None)
    if rank is not None and (not park["ranks"] or park["ranks"][-1] != int(rank.group(1))):
        park["ranks"].append(int(rank.group(1)))
    stretch = dream_park.offline_stretch(task)
    if stretch is not None:
        park["stretch"] = stretch
    rate = dream_park.profit_rate(task)
    if rate is not None:
        park["rate"] = rate
    wanted, park["rank_wanted"] = park["rank_wanted"], None
    if emotions is not None:
        park["emotions"], park["emotions_at"] = emotions, park["upgrades"]
        values, target = emotions
        if wanted is not None and (target != wanted or any(value < target for value in values)):
            park["rank_unmet"].add(wanted)
        if all(value >= target for value in values) and park["rank_checked"] != target:
            return press_once(task, PARK_RANK)
    elif wanted is not None:
        # The header said every emotion reached this target, but the panel does not read them, so Rank Up cannot be
        # checked. Counting the target as tried keeps a later reading of the panel at that target from opening the Rank.
        park["rank_checked"] = wanted
    park["phase"] = TO_OPERATE
    return press_once(task, PARK_OPERATE)


def ride_risen(task, rows):
    """Check the last upgrade or build took, once its level has had time to rise.

    Args:
        task: The Daily task.
        rows: The Facilities rows now in view.

    Returns:
        None to go on, True to wait for the level, or the stop's claim of the frame after two presses without a rise.
    """
    park = park_state(task)
    pending = park["pending"]
    if pending is None:
        return None
    name, level, pressed, action = pending
    ride = next((ride for ride in rows if ride.name == name), None)
    if ride is not None and ride.level > level:
        park["pending"], park["no_rise"][name] = None, 0
        if action == dream_park.BUILD:
            park["builds"].append(name)
        return None
    if time.monotonic() - pressed < UPGRADE_WAIT:
        return True
    park["pending"] = None
    park["no_rise"][name] += 1
    if park["no_rise"][name] >= 2:
        return stop(task, f"Stopped: Dream Park did not take two presses on {name} (its level did not rise). Check the game, then press Start again.")
    return None


def leave_facilities(task, note):
    """Stop upgrading for this visit and close the Facilities list."""
    park = park_state(task)
    if park["scrolls"]:
        note += f" (the list dragged {park['scrolls']} time{'s' if park['scrolls'] != 1 else ''})"
    park["phase"], park["note"] = TO_LEAVE, note
    return press_once(task, PANEL_CLOSE)


def may_scroll(task, rows, reason):
    """Say whether a short drag down the Facilities list may bring the ride `choose` wants into view.

    Only when the ride it wants is not in view, no row in view waits on its price, the lowest row is cut off at the
    bottom, no locked ride shows, the last drag moved the list and left rows to read, this opening of the list and the
    visit have drags left, and the drag lets go where it ends, which ok-script's PostMessage input does.

    Args:
        task: The Daily task.
        rows: The Facilities rows now in view.
        reason: Why `choose` pressed nothing.

    Returns:
        True when the list may be dragged.
    """
    park = park_state(task)
    if not dream_park.NOT_IN_VIEW.fullmatch(reason) or park["opening_scrolls"] >= SCROLL_CAP or park["scrolls"] >= SCROLL_VISIT_CAP:
        return False
    if any(ride.price is None and ride.level < dream_park.MAX_LEVEL for ride in rows):
        return False
    if not dream_park.cut_off_below(task) or dream_park.locked_in_view(task):
        return False
    if park["opening_scrolls"] and (not rows or unmoved(park["scroll_names"], dream_park.row_names(task))):
        return False
    return lets_go(task)


def lets_go(task):
    """Say whether a drag lets go where it ends, which ok-script's PostMessage input does."""
    return isinstance(getattr(task.executor, "interaction", None), PostMessageInteraction)


def unmoved(before, after):
    """Say whether two reads of the list show the same ride names at the same places."""
    return (before is not None and len(before) == len(after)
            and all(a[0] == b[0] and abs(a[1] - b[1]) < SCROLL_MOVED for a, b in zip(before, after)))


def scroll_facilities(task):
    """Drag the Facilities list a short way down, through ok-script's own swipe, so the rows below it come into view."""
    park = park_state(task)
    park["scrolls"] += 1
    park["opening_scrolls"] += 1
    park["scroll_names"] = dream_park.row_names(task)
    task.log_info(f"dragging the Facilities list from {dream_park.SCROLL_FROM} to {dream_park.SCROLL_TO} ({park['opening_scrolls']} of {SCROLL_CAP} "
                  f"this opening, {park['scrolls']} of {SCROLL_VISIT_CAP} this visit)")
    task.swipe_relative(*dream_park.SCROLL_FROM, *dream_park.SCROLL_TO, duration=DRAG_DURATION)
    park["scrolled"] = time.monotonic()
    return True


def handle_daily_facilities(task):
    """Build or upgrade one ride per pass with the park's profit, re-reading the list after every press.

    Any box reading as Crystals, a currency or a purchase in a row's price column, or anywhere on the list's right side,
    stops Daily, and a row whose price does not read is never pressed. When every emotion has reached its target and its
    Rank Up has not been tried at that target, the visit goes to the Manage panel first, at most once for each target in
    a visit, however the targets the header reads come and go. Once tried without a rank up, the list is left with no
    press; the upgrades go on only when the Manage panel read an emotion below that target or read another target, or
    that target was just ranked up. When the ride `choose` wants may be further down, the list is dragged a short way
    and given time to come to rest before its rows count. Once a build is done and before any upgrade, or before leaving
    the list, the visit makes its one trip to the Skill tab, when the Manage panel's rate has read.
    """
    if showing(task, FACILITIES_TITLE) is None or showing(task, FACILITIES_HINT) is None:
        return False
    reopened = park_state(task)["screen"] != "facilities"
    shown_for = arrive(task, "facilities")
    park = park_state(task)
    if reopened:
        # The list opens at its top each time, so names read before an earlier drag say nothing of this opening, and
        # the ride it needs may again sit a drag down.
        park["scroll_names"], park["scrolled"], park["opening_scrolls"] = None, None, 0
    if not park_active(task) or park["phase"] == TO_LEAVE:
        return press_once(task, PANEL_CLOSE)
    if park["phase"] == TO_MANAGE:
        return press_once(task, PARK_MANAGE)
    rows = dream_park.facility_rows(task)
    for ride in rows:
        hit = next((box for box in ride.price_column if refused(box.name)), None)
        if hit is not None:
            return stop(task, f"Stopped: a Dream Park price reads {hit.name!r}, and Daily spends only the park's profit. Check the game, then press Start again.")
    hit = next((box for box in dream_park.list_side(task) if refused(box.name)), None)
    if hit is not None:
        return stop(task, f"Stopped: the Dream Park list reads {hit.name!r}, and Daily spends only the park's profit. Check the game, then press Start again.")
    if park["scrolled"] is not None and time.monotonic() - park["scrolled"] < SETTLE:
        return True
    waiting = ride_risen(task, rows)
    if waiting is not None:
        return waiting
    emotions = dream_park.header_emotions(task)
    if emotions is None and park["emotions_at"] == park["upgrades"]:
        emotions = park["emotions"]
    if (emotions is not None and all(value >= emotions[1] for value in emotions[0]) and park["rank_checked"] != emotions[1]
            and emotions[1] not in park["rank_sent"]):
        # At most one trip for each target in a visit: when the Manage panel reads an emotion below the target the
        # header shows, or does not read at all, another trip for that target would read the same and send the visit
        # back here, round and round until the visit runs out of time, also when the header reads two targets by turns.
        park["phase"], park["rank_wanted"] = TO_MANAGE, emotions[1]
        park["rank_sent"].add(emotions[1])
        return press_once(task, PARK_MANAGE)
    if (emotions is not None and all(value >= emotions[1] for value in emotions[0]) and emotions[1] not in park["rank_unmet"]
            and emotions[1] not in park["ranked"]):
        # Each Rank so far has brought a new ride with a large build price, so the profit waits for that ride rather
        # than going on the cheapest rides while the Rank Up the header shows as earned stays untaken. An AI Automation
        # level that passes its price rule earns its price back by the next visit, so it is bought all the same.
        if skill_due(task):
            return press_once(task, SKILL_TAB)
        return leave_facilities(task, f"every emotion is at Rank target {emotions[1]}, but its Rank Up was not taken, so the profit is kept for the next Rank's ride; check the park's Rank screen if this repeats")
    if park["upgrades"] >= UPGRADE_CAP:
        return leave_facilities(task, f"the visit's {UPGRADE_CAP} upgrades are used")
    ride, reason = dream_park.choose(rows, emotions, dream_park.profit(task), park["stretch"])
    if ride is None:
        if shown_for < SETTLE:
            return True
        if may_scroll(task, rows, reason):
            return scroll_facilities(task)
        if skill_due(task):
            return press_once(task, SKILL_TAB)
        return leave_facilities(task, reason)
    if ride.action != dream_park.BUILD and skill_due(task):
        return True if shown_for < SETTLE else press_once(task, SKILL_TAB)
    park["pending"] = (ride.name, ride.level, time.monotonic(), ride.action)
    if ride.action == dream_park.BUILD:
        return press(task, BUILD, ride.button)
    park["upgrades"] += 1
    return press(task, UPGRADE, ride.button, ride.level)


def skill_due(task):
    """Say whether the visit still owes its one trip to the Skill tab, which needs the Manage panel's rate."""
    park = park_state(task)
    return not park["skill_done"] and park["rate"] is not None


def skill_risen(task, skills):
    """Check the last skill press took, once its level has had time to rise.

    Args:
        task: The Daily task.
        skills: The Skill tab's rows now in view.

    Returns:
        None to go on, True to wait for the level, or the claim of the frame leaving the tab after two presses without
        a rise.
    """
    park = park_state(task)
    pending = park["skill_pending"]
    if pending is None:
        return None
    pattern, level, pressed = pending
    happy = pattern is dream_park.ANOTHER_HAPPY_DAY
    skill = next((skill for skill in skills if pattern.fullmatch(skill.name)), None)
    if skill is not None and skill.level is not None and skill.level > level:
        park["skill_pending"], park["skill_no_rise"] = None, 0
        park["happy_levels" if happy else "skill_levels"].append(skill.level)
        return None
    if time.monotonic() - pressed < UPGRADE_WAIT:
        return True
    park["skill_pending"] = None
    park["skill_no_rise"] += 1
    if park["skill_no_rise"] >= 2:
        return leave_skills(task, NO_HAPPY_DAY_RISE if happy else NO_SKILL_RISE)
    return None


def leave_skills(task, note):
    """End the visit's Skill tab trip and go back to the Facilities list."""
    park = park_state(task)
    park["skill_done"], park["skill_note"] = True, note
    task.log_info(f"leaving the Skill tab: {note}")
    return press_once(task, FACILITIES_TAB)


def happiness_left(task):
    """Say how many Another Happy Day levels the trip may still buy.

    Args:
        task: The Daily task.

    Returns:
        The Happiness the header shows short while it lags the most, never past what it was short when first weighed
        less the levels bought since; 0 when the header does not read.
    """
    park = park_state(task)
    short = dream_park.happiness_short(dream_park.header_emotions(task))
    if short and park["happy_need"] is None:
        park["happy_need"] = short
    if park["happy_need"] is None:
        return 0
    return min(short, park["happy_need"] - len(park["happy_levels"]))


def may_scroll_skills(task):
    """Say whether a short drag down the Skill tab may bring Another Happy Day's button into view.

    Only when the lowest name is cut off at the bottom, no locked skill shows, the last drag moved the list, the trip
    has drags left, and the drag lets go where it ends.
    """
    park = park_state(task)
    if park["skill_scrolls"] >= SKILL_SCROLL_CAP or not dream_park.cut_off_below(task) or dream_park.locked_in_view(task):
        return False
    if park["skill_scrolls"] and unmoved(park["skill_scroll_names"], dream_park.row_names(task)):
        return False
    return lets_go(task)


def scroll_skills(task):
    """Drag the Skill tab a short way down, as the Facilities list is dragged."""
    park = park_state(task)
    park["skill_scrolls"] += 1
    park["skill_scroll_names"] = dream_park.row_names(task)
    task.log_info(f"dragging the Skill tab from {dream_park.SCROLL_FROM} to {dream_park.SCROLL_TO} ({park['skill_scrolls']} of {SKILL_SCROLL_CAP})")
    task.swipe_relative(*dream_park.SCROLL_FROM, *dream_park.SCROLL_TO, duration=DRAG_DURATION)
    park["skill_scrolled"] = time.monotonic()
    return True


def handle_daily_skill_tab(task):
    """Upgrade AI Automation one level per pass while a level pays for itself by the next visit, then Another Happy Day
    while Happiness lags, then go back to Facilities.

    Any box reading as Crystals, a currency or a purchase in a row's price column, or anywhere on the panel's right
    side, stops Daily. AI Automation's own Upgrade is pressed first, with taps. Then, while Happiness lags the other
    emotions and the next Rank's target, Another Happy Day's Acquire or Upgrade, one level per point still short and
    under AI Automation's budget, the tab dragged a short way down when its button is below the edge. Two presses
    without a level rise, the visit's press cap, or a tab that does not read end the trip with no further press.
    """
    if showing(task, SKILL_TITLE) is None or showing(task, FACILITIES_HINT) is None:
        return False
    shown_for = arrive(task, "skill")
    park = park_state(task)
    if not park_active(task) or park["phase"] != TO_OPERATE or park["skill_done"]:
        return press_once(task, FACILITIES_TAB)
    skills = dream_park.skill_rows(task)
    for skill in skills:
        hit = next((box for box in skill.price_column if refused(box.name)), None)
        if hit is not None:
            return stop(task, f"Stopped: a Dream Park price reads {hit.name!r}, and Daily spends only the park's profit. Check the game, then press Start again.")
    hit = next((box for box in dream_park.list_side(task) if refused(box.name)), None)
    if hit is not None:
        return stop(task, f"Stopped: the Dream Park Skill tab reads {hit.name!r}, and Daily spends only the park's profit. Check the game, then press Start again.")
    if shown_for < SETTLE or (park["skill_scrolled"] is not None and time.monotonic() - park["skill_scrolled"] < SETTLE):
        return True
    waiting = skill_risen(task, skills)
    if waiting is not None:
        return waiting
    if park["skill_presses"] >= SKILL_CAP:
        return leave_skills(task, f"the visit's {SKILL_CAP} AI Automation presses are used")
    money = dream_park.profit(task)
    skill, reason = dream_park.choose_skill(skills, money, park["rate"])
    if skill is not None:
        park["skill_pending"] = (dream_park.AI_AUTOMATION, skill.level, time.monotonic())
        park["skill_presses"] += 1
        return press(task, SKILL_UPGRADE, skill.button)
    if happiness_left(task) <= 0:
        return leave_skills(task, reason)
    if park["happy_presses"] >= SKILL_CAP:
        return leave_skills(task, f"{reason}; the visit's {SKILL_CAP} Another Happy Day presses are used")
    happy, why = dream_park.choose_happy_day(skills, money, park["rate"])
    if happy is not None:
        park["skill_pending"] = (dream_park.ANOTHER_HAPPY_DAY, happy.level or 0, time.monotonic())
        park["happy_presses"] += 1
        return press(task, HAPPY_DAY_UPGRADE, happy.button)
    if why == dream_park.HAPPY_DAY_NOT_IN_VIEW and may_scroll_skills(task):
        return scroll_skills(task)
    return leave_skills(task, f"{reason}; {why}")


def handle_daily_park_view(task):
    """Open the panel the visit needs next from the park view, or leave the park."""
    if showing(task, PARK_MANAGE_TAB) is None or showing(task, PARK_OPERATE_TAB) is None:
        return False
    arrive(task, "park")
    park = park_state(task)
    if not park_active(task) or park["phase"] == TO_LEAVE:
        return press_once(task, PARK_LEAVE)
    return press_once(task, PARK_MANAGE if park["phase"] == TO_MANAGE else PARK_OPERATE)


def handle_daily_park_achievements(task):
    """Press every orange claim ring on both tabs of the event's achievements, then go back to the event page."""
    if showing(task, ACHIEVEMENTS_TITLE) is None:
        return False
    shown_for = arrive(task, "achievements")
    park = park_state(task)
    if not park_active(task) or park["claims_done"]:
        return press_once(task, ACHIEVEMENTS_LEAVE)
    now = time.monotonic()
    if park["claim_pressed"] is not None:
        if now - park["claim_pressed"] < CLAIM_WAIT:
            return True
        park["claim_pressed"] = None
        park["claim_misses"] += 1
        if park["claim_misses"] >= 2:
            return stop(task, "Stopped: two Dream Park achievement claims opened nothing. Check the game, then press Start again.")
    if shown_for < SETTLE or (MANAGEMENT_TAB in park["pressed"] and now - park["pressed"][MANAGEMENT_TAB] < NAV_WAIT):
        return True
    ready = dream_park.ready_claims(task, frame_of(task))
    if ready:
        x, y = ready[0][0] * task.width, ready[0][1] * task.height
        park["claim_pressed"] = now
        return press(task, CLAIM, Spot("claim ring", x - 1, y - 1, 2, 2))
    if MANAGEMENT_TAB not in park["pressed"]:
        return press_once(task, MANAGEMENT_TAB)
    park["claims_done"] = True
    return press_once(task, ACHIEVEMENTS_LEAVE)


def handle_daily_event_page(task):
    """Enter the park, then open its achievements, then go back to the Lobby; end the step quietly when it cannot be entered."""
    if showing(task, PARK_TITLE) is None or showing(task, EVENT_TITLE) is None:
        return False
    shown_for = arrive(task, "event page")
    park = park_state(task)
    if not park_active(task):
        return press_once(task, PAGE_LEAVE)
    enter = showing(task, PARK_ENTER)
    if enter is None:
        if shown_for < SETTLE:
            return True
        end_park(task, "Dream Park is not running")
        return press_once(task, PAGE_LEAVE)
    if park["phase"] != TO_LEAVE:
        return press_once(task, ENTER_PARK, enter)
    achievements = showing(task, PARK_ACHIEVEMENTS_BUTTON)
    if not park["claims_done"] and achievements is not None:
        return press_once(task, PARK_ACHIEVEMENTS, achievements)
    end_park(task)
    return press_once(task, PAGE_LEAVE)


def handle_daily_captain_page(task):
    """Claim each reached tier on The Path of a Captain, then hand the Event list over to Dream Park.

    Only a tier whose button reads `Claim Reward` is pressed; `Claimed` and `Insufficient level` are left. Once nothing
    reads ready, the page is the Event list's to work on, which opens Dream Park from it.
    """
    if showing(task, CAPTAIN_TITLE) is None or showing(task, EVENT_TITLE) is None:
        return False
    claims = claims_state(task)
    if not park_active(task) or claims["captain"] is not None:
        return False
    shown_for = arrive_claim_screen(task, "captain page", (MENU, EVENT, CAPTAIN_ENTRY))
    waiting = claim_outcome(task)
    if waiting is not None:
        return waiting
    if shown_for < SETTLE:
        return True
    settle_recount(task, ("captain",))
    ready = captain_claims(task)
    if ready:
        return press_claim(task, CAPTAIN_CLAIM, "captain", ready[0], len(ready))
    claims["captain"] = "visited"
    return False


def handle_daily_event_list(task):
    """Open The Path of a Captain, then Dream Park, from the Event list, which opens on another event.

    A list without The Path of a Captain goes straight on to Dream Park, and one without Dream Park ends the step quietly.
    """
    if showing(task, EVENT_TITLE) is None or showing(task, EVENT_HEADING) is None:
        return False
    shown_for = arrive(task, "event list")
    if not park_active(task):
        return press_once(task, EVENT_LEAVE)
    claims = claims_state(task)
    if claims["captain"] is None:
        captain = text_in_region(task, CAPTAIN_ENTRY_TEXT, dream_park.EVENT_LIST_REGION)
        if captain is not None:
            return press_once(task, CAPTAIN_ENTRY, captain)
        if shown_for < SETTLE:
            return True
        task.log_info("The Path of a Captain is not in the Event list, so its tiers are skipped")
        claims["captain"] = "not listed"
    entry = dream_park.event_entry(task)
    if entry is not None:
        return press_once(task, DREAM_PARK, entry)
    if shown_for < SETTLE:
        return True
    end_park(task, "Dream Park is not running")
    return press_once(task, EVENT_LEAVE)


def invest_state(task):
    """Give the invest step's state."""
    return run_state(task)["invest"]


def setting(task, key, default):
    """Read one of Daily's settings, or its default where the task has no config."""
    config = getattr(task, "config", None)
    return config.get(key, default) if config is not None else default


def invest_goals(task):
    """Give the goal units, read from the setting once a run and checked against the game's combatants."""
    inv = invest_state(task)
    if inv["goals"] is None:
        goals = invest.goal_units(setting(task, GOALS_SETTING, []))
        if goals.unknown:
            task.log_info(f"the goal list names {', '.join(goals.unknown)}, which the game data does not know, so they are left out")
            inv["notes"].append(f"left out {', '.join(goals.unknown)} (not a known Combatant)")
        floor = setting(task, FLOOR_SETTING, UNITS_FLOOR)
        inv["goals"] = goals.units
        inv["floor"] = floor if isinstance(floor, int) and not isinstance(floor, bool) and floor >= 0 else UNITS_FLOOR
    return inv["goals"]


def invest_active(task):
    """Say whether the invest step is the chore under way with a goal list to work through."""
    step = pending_step(task)
    return step is not None and step.name == INVEST and bool(invest_goals(task))


def invest_arrive(task, kind, signature):
    """Note that an invest screen reads in full: restart the unknown-screen clock and count afresh the targets that lead to it.

    A different screen or panel state from the one the last corner or node press was made on frees that place again.

    Args:
        task: The Daily task.
        kind: A key of `INVEST_ARRIVALS`, or "card".
        signature: What the screen reads, compared from pass to pass.

    Returns:
        How long, in seconds, this exact reading has shown.
    """
    recognised(task)
    taps = run_state(task)["taps"]
    for target in INVEST_ARRIVALS.get(kind, ()):
        taps[target] = 0
    inv = invest_state(task)
    now = time.monotonic()
    if inv["screen"] != signature:
        inv["screen"], inv["since"] = signature, now
    if not guard_holds(task, signature):
        inv["guard"] = None
    return now - inv["since"]


def guard_holds(task, signature):
    """Say whether the last corner or node press still bars that place on this reading.

    Only another screen frees it, or on a spend panel another state of it: a Stats tab, Partners tab, list or map read
    again, however its OCR wavers, is the screen the press was made on.

    Args:
        task: The Daily task.
        signature: The screen's reading now, its kind first.

    Returns:
        True while the press must not be repeated.
    """
    guard = invest_state(task)["guard"]
    if guard is None or guard[0] != signature[0]:
        return False
    return guard == signature or signature[0] in STEADY_SCREENS


def press_invest(task, target, box=None):
    """Press an invest target through `press`, refusing first any box under it that reads as a control no invest press may touch.

    Args:
        task: The Daily task.
        target: A key of `TARGETS`.
        box: The OCR box for a text button, None for a fixed point.

    Returns:
        True, which claims the frame.
    """
    point = centre_of(box, task.width, task.height) if box is not None else TARGETS[target]
    for hit in ([box] if box is not None else []) + boxes_at(task, point):
        marker = invest.refused(hit.name)
        if marker:
            task.log_info(f"not pressing {target}: the box there reads {hit.name!r} ({marker!r})")
            return stop(task, f"Stopped: {target} would have pressed {hit.name!r}. Check the game, then press Start again.")
    return press(task, target, box)


def press_invest_once(task, target, box=None):
    """Press an invest target, unless it was pressed moments ago on a screen that still reads the same, and may still be changing."""
    inv = invest_state(task)
    now = time.monotonic()
    last = inv["pressed"].get(target)
    if last is not None and now - last[0] < NAV_WAIT and last[1] == inv["screen"]:
        return True
    inv["pressed"][target] = (now, inv["screen"])
    return press_invest(task, target, box)


def guarded_press(task, target, box, signature, opening=True):
    """Make a press that must not be repeated on the screen it was made on: a corner press, or a node's opening press.

    The Stats tab's Promotions and Level Up open a panel whose own button sits on the same spot, so a second tap while the
    panel draws would spend unread.

    Args:
        task: The Daily task.
        target: A key of `TARGETS`.
        box: The OCR box, None for a fixed point.
        signature: The screen's reading, which must change before that place is pressed again.
        opening: Whether the press opens a panel or node, whose wait `opening_waits` then times.

    Returns:
        True, which claims the frame.
    """
    inv = invest_state(task)
    if guard_holds(task, signature):
        return True
    inv["guard"] = signature
    if opening:
        inv["visit"]["opened"] = time.monotonic()
    return press_invest(task, target, box)


def new_visit(unit, index):
    """Start one goal unit's visit.

    Returns:
        A dict: the unit and its place in the goal list, whether the Stats tab has read its name since the last screen
        Daily did not know, whether that ever happened, where the visit stands, when the last guarded press was made, the
        spends per action, the actions whose panel was read and left, those whose spend changed nothing, when Auto Register
        was pressed, whether its Promotion ended ready but for the Units and whether below its cap, its Partner's name and what its
        `强化` was pressed for, the node opened and the nodes done.
    """
    return {"unit": unit, "index": index, "checked": False, "arrived": False, "phase": TO_PROMOTE, "opened": None, "spent": Counter(),
            "read": set(), "no_effect": set(), "registered": None, "units_short": False, "below_cap": None, "partner": None,
            "partner_action": None, "node": None, "nodes_done": set()}


def note(task, text):
    """Log a line and keep it for the finish line's invest part."""
    task.log_info(text)
    invest_state(task)["notes"].append(text)


def end_visit(task, why=None):
    """End the goal unit's visit and move on to the next, holding later units' Level Up back when it ended unread, below its cap,
    or with its Promotion ready but for the Units, the one thing a Promotion and a Level Up both spend.

    Args:
        task: The Daily task.
        why: Why it ended early, for the finish line, or None.
    """
    inv = invest_state(task)
    visit = inv["visit"]
    if why is not None:
        note(task, why)
    if not visit["arrived"] or visit["units_short"] or visit["below_cap"] is not False:
        inv["held"].add(visit["unit"])
    visit["phase"], visit["checked"] = VISITED, False
    inv["index"] = visit["index"] + 1


def level_held(task):
    """Say whether this goal unit must leave its Level Up for a unit listed before it."""
    inv = invest_state(task)
    return not invest.level_allowed(inv["goals"], inv["visit"]["index"], inv["held"])


def record_short(task, action, have, need, units, caption_box, reason):
    """Keep a short action for the goal file and the finish line.

    The goal file gets a line only when the button reads something other than its go word: a met counter under the Units
    floor, or a go word Daily did not press, writes none.

    Args:
        task: The Daily task.
        action: One of the `invest` action names.
        have: The counter's first number.
        need: Its second.
        units: The Units cost.
        caption_box: The button's box.
        reason: Why it was not pressed.
    """
    inv = invest_state(task)
    visit = inv["visit"]
    caption = folded(caption_box.name)
    task.log_info(f"not investing in {visit['unit']}: {action}, {reason}")
    if caption in (invest.PROMOTE_WORD, invest.ACTIVATE_WORD):
        inv["notes"].append(f"{visit['unit']} {action}: {reason}")
        return
    stage = invest.stage_for(visit["unit"], action, visit["partner"], caption)
    inv["lines"][(visit["unit"], action)] = invest.goal_line(visit["unit"], action, have, need, units, caption_box.name.strip(), stage,
                                                             datetime.now().isoformat(timespec="seconds"))


def spend(task, target, box, action, signature, detail):
    """Press a spend, log it, and wait for its effect.

    Args:
        task: The Daily task.
        target: `PROMOTE`, `LEVEL_UP` or `ACTIVATE`.
        box: The button's box.
        action: One of the `invest` action names.
        signature: The panel's reading, which its effect must change.
        detail: The counter, cost and Units, for the log.

    Returns:
        True, which claims the frame.
    """
    inv = invest_state(task)
    visit = inv["visit"]
    visit["spent"][action] += 1
    inv["spend"] = {"action": action, "signature": signature, "at": time.monotonic()}
    task.log_info(f"investing in {visit['unit']}: {action}, {detail}")
    return guarded_press(task, target, box, signature, opening=False)


def amount(value):
    """Write a Units figure for the log, `70,000`, or say it did not read."""
    return f"{value:,}" if isinstance(value, int) else "unread"


def took_effect(task):
    """Count the awaited spend as done."""
    inv = invest_state(task)
    inv["spends"].append((inv["visit"]["unit"], inv["spend"]["action"]))
    inv["spend"], inv["misses"] = None, 0


def awaiting_spend(task, signature):
    """Settle the awaited spend against the screen: its effect shows once the panel reads differently.

    Args:
        task: The Daily task.
        signature: The panel's reading now.

    Returns:
        True while the spend's wait runs on an unchanged panel, or once Daily has stopped: press nothing. False otherwise;
        a spend that changed nothing is then left in the visit's `no_effect`.
    """
    inv = invest_state(task)
    pending = inv["spend"]
    if pending is None:
        return False
    if signature != pending["signature"]:
        took_effect(task)
        return False
    if time.monotonic() - pending["at"] < SPEND_WAIT:
        return True
    inv["spend"] = None
    inv["misses"] += 1
    inv["visit"]["no_effect"].add(pending["action"])
    note(task, f"{inv['visit']['unit']}: {pending['action']} changed nothing")
    if inv["misses"] >= NO_EFFECT_STOP:
        return stop(task, f"Stopped: {NO_EFFECT_STOP} upgrade presses in a row changed nothing. Check the game, then press Start again.")
    return False


def end_invest(task):
    """Write the goal file with every short action, in goal order, once every goal unit is visited. The step is done back on the Lobby."""
    inv = invest_state(task)
    inv["ended"] = True
    order = {unit: place for place, unit in enumerate(inv["goals"])}
    lines = [inv["lines"][key] for key in sorted(inv["lines"], key=lambda key: order.get(key[0], len(order)))]
    try:
        invest.write_goals(lines)
    except Exception as error:
        logger.warning(f"could not write {invest.GOALS_FILE}: {error}")
        inv["unwritten"] = str(error)


def invest_summary(inv):
    """Say in a few words what the invest step did, for the finish line: each unit's spends and first shortfall, then the rest.

    Args:
        inv: The invest step's state.

    Returns:
        The words, or None when there was no goal list.
    """
    if not inv["goals"]:
        return None
    parts = []
    for unit in inv["goals"]:
        spent = Counter(action for who, action in inv["spends"] if who == unit)
        short = next((line for (who, _), line in inv["lines"].items() if who == unit), None)
        words = ", ".join(f"{action} x{count}" if count > 1 else action for action, count in spent.items()) or "nothing spent"
        if short is not None:
            words += f", short: {short['action']} {short['have']}/{short['need']} ({short['caption']})"
        parts.append(f"{unit}: {words}")
    summary = "Invest: " + "; ".join(parts)
    stageless = [f"{line['unit']} {line['action']} ({line['caption']})" for line in inv["lines"].values() if not line["stage"]]
    if stageless:
        summary += f"; no farming stage for {', '.join(stageless)}"
    if inv["notes"]:
        summary += f" ({'; '.join(inv['notes'])})"
    if inv["unwritten"]:
        summary += f" (the goal file was not written: {inv['unwritten']})"
    return summary


def tab_press(task, word, region, target):
    """Press one of the Details screen's left tabs by its caption, or leave Details when it does not read."""
    box = invest.equal_in(task, word, region)
    if box is None:
        end_visit(task, f"{invest_state(task)['visit']['unit']}: the {word.title()} tab did not read")
        return press_invest_once(task, DETAILS_LEAVE)
    return press_invest_once(task, target, box)


def to_phase(task):
    """Head for the Details tab where the visit stands: Stats for its own rows, Partners, Potential, or out once visited."""
    phase = invest_state(task)["visit"]["phase"]
    if phase in (TO_PROMOTE, TO_LEVEL):
        return tab_press(task, "stats", invest.STATS_TAB_REGION, STATS_TAB)
    if phase == TO_PARTNER:
        return tab_press(task, "partners", invest.PARTNERS_TAB_REGION, PARTNERS_TAB)
    if phase == TO_POTENTIAL:
        return tab_press(task, "potential", invest.POTENTIAL_TAB_REGION, POTENTIAL_TAB)
    return press_invest_once(task, DETAILS_LEAVE)


def opening_waits(task, signature, what):
    """Wait for a panel or node an opening press asked for, skipping the unit once it has not shown in time.

    Args:
        task: The Daily task.
        signature: The screen's reading now.
        what: The press's words, for the note.

    Returns:
        True while it waits, False once the screen has changed since the press, None once the unit was skipped.
    """
    inv = invest_state(task)
    visit = inv["visit"]
    if visit["opened"] is None:
        return False
    if not guard_holds(task, signature):
        visit["opened"] = None
        return False
    if time.monotonic() - visit["opened"] < PANEL_WAIT:
        return True
    visit["opened"] = None
    end_visit(task, f"{visit['unit']}: {what} did not open")
    return None


def handle_daily_invest_card(task):
    """Close a card an upgrade put up, by its caption, never the `进入` the Return item card reads under it."""
    if not invest_active(task):
        return False
    card = invest.result_card(task)
    if card is None:
        return False
    invest_arrive(task, "card", ("card", card.kind))
    if invest_state(task)["spend"] is not None:
        took_effect(task)
    return press_invest_once(task, RESULT_CLOSE, card.caption_box)


def handle_daily_invest_list(task):
    """Open the next goal unit's card on the Combatant List's visible row, or leave once every goal unit is visited.

    A goal unit whose name is not on the row is skipped with a note: the list is never dragged or re-sorted.
    """
    if not invest_active(task) or not invest.combatant_list(task):
        return False
    shown_for = invest_arrive(task, "list", ("list",))
    inv = invest_state(task)
    visit = inv["visit"]
    if visit is not None and visit["phase"] != VISITED and visit["arrived"]:
        end_visit(task, f"{visit['unit']}: back on the Combatant List before its visit ended")
    elif visit is not None:
        visit["checked"] = False
    goals = inv["goals"]
    while inv["index"] < len(goals) and not inv["ended"]:
        unit = goals[inv["index"]]
        point = invest.card_point(task, unit)
        if point is None:
            if shown_for < SETTLE:
                return True
            if inv["visit"] is None or inv["visit"]["unit"] != unit:
                inv["visit"] = new_visit(unit, inv["index"])
            end_visit(task, f"{unit}: not on the Combatant List's visible row")
            continue
        if inv["visit"] is None or inv["visit"]["unit"] != unit:
            inv["visit"] = new_visit(unit, inv["index"])
            taps = run_state(task)["taps"]
            for target in INVEST_SPENDS:
                taps[target] = 0
        x, y = point[0] * task.width, point[1] * task.height
        return press_invest_once(task, UNIT_CARD, Spot(unit, x - 1, y - 1, 2, 2))
    if not inv["ended"]:
        end_invest(task)
    return press_invest_once(task, LIST_LEAVE)


def handle_daily_invest_stats(task):
    """Check the goal unit's name on its Stats tab, then open its Promotion or Level Up, or go on to its Partner and Potential.

    The name is the one place these screens say whose they are, so every later press of the visit rests on this check.
    """
    if not invest_active(task):
        return False
    stats = invest.stats_screen(task)
    if stats is None:
        return False
    signature = ("stats", folded(stats.name), stats.level, stats.cap, stats.caption)
    invest_arrive(task, "stats", signature)
    visit = invest_state(task)["visit"]
    if visit is None or visit["phase"] == VISITED:
        return press_invest_once(task, DETAILS_LEAVE)
    if not invest.same_name(stats.name, visit["unit"]):
        end_visit(task, f"{visit['unit']}: skipped, its card opened {stats.name}")
        return press_invest_once(task, DETAILS_LEAVE)
    visit["checked"] = visit["arrived"] = True
    visit["below_cap"], visit["registered"] = stats.level < stats.cap, None
    waiting = opening_waits(task, signature, "its upgrade panel")
    if waiting is None:
        return press_invest_once(task, DETAILS_LEAVE)
    if waiting:
        return True
    if visit["phase"] == TO_PROMOTE:
        if stats.level == stats.cap and stats.caption == invest.PROMOTE_WORD and invest.PROMOTION not in visit["read"]:
            return guarded_press(task, OPEN_PROMOTION, stats.caption_box, signature)
        visit["phase"] = TO_LEVEL
    if visit["phase"] == TO_LEVEL:
        if stats.level < stats.cap and stats.caption == invest.LEVEL_UP_WORD and invest.LEVEL not in visit["read"]:
            if not level_held(task):
                return guarded_press(task, OPEN_LEVEL_UP, stats.caption_box, signature)
            note(task, f"{visit['unit']}: Level Up left for a goal unit listed before it")
            visit["read"].add(invest.LEVEL)
        visit["phase"] = TO_PARTNER
    return to_phase(task)


def handle_daily_invest_partners(task):
    """Open the goal unit's Partner's Promotion or Level Up with `强化`, never `Change`, then go on to Potential, at once when it has no Partner."""
    if not invest_active(task):
        return False
    partner = invest.partners_tab(task)
    if partner is None:
        return invest.no_partner_tab(task) and no_partner(task)
    signature = ("partners", folded(partner.name), partner.level, partner.cap, partner.upgrade_box is not None)
    invest_arrive(task, "partners", signature)
    visit = invest_state(task)["visit"]
    if visit is None or visit["phase"] == VISITED:
        return press_invest_once(task, DETAILS_LEAVE)
    if not visit["checked"]:
        return tab_press(task, "stats", invest.STATS_TAB_REGION, STATS_TAB)
    visit["partner"], visit["registered"] = partner.name, None
    waiting = opening_waits(task, signature, "its Partner's upgrade panel")
    if waiting is None:
        return press_invest_once(task, DETAILS_LEAVE)
    if waiting:
        return True
    if visit["phase"] == TO_PARTNER:
        action = invest.PARTNER_PROMOTION if partner.level == partner.cap else invest.PARTNER_LEVEL
        if action not in visit["read"] and action not in visit["no_effect"]:
            if action == invest.PARTNER_LEVEL and level_held(task):
                note(task, f"{visit['unit']}: its Partner's Level Up left for a goal unit listed before it")
            elif partner.upgrade_box is None:
                note(task, f"{visit['unit']}: the Partner's 强化 did not read on its own")
            else:
                visit["partner_action"] = action
                return guarded_press(task, PARTNER_UPGRADE, partner.upgrade_box, signature)
        visit["phase"] = TO_POTENTIAL
    return to_phase(task)


def no_partner(task):
    """Go on to Potential from a Partners tab that offers only `Assign Partner`, which is never pressed."""
    invest_arrive(task, "partners", ("partners", None))
    visit = invest_state(task)["visit"]
    if visit is None or visit["phase"] == VISITED:
        return press_invest_once(task, DETAILS_LEAVE)
    if not visit["checked"]:
        return tab_press(task, "stats", invest.STATS_TAB_REGION, STATS_TAB)
    if visit["phase"] == TO_PARTNER:
        note(task, f"{visit['unit']}: no Partner assigned")
        visit["phase"] = TO_POTENTIAL
    return to_phase(task)


def leave_panel(task, owner, action):
    """Count a panel's action as read and leave the panel, the visit moving on past it.

    Args:
        task: The Daily task.
        owner: "combatant" or "partner".
        action: The action just read.

    Returns:
        True, which claims the frame.
    """
    visit = invest_state(task)["visit"]
    visit["read"].add(action)
    if owner == "partner":
        visit["phase"] = TO_POTENTIAL
    elif action == invest.LEVEL or visit["phase"] == TO_LEVEL:
        visit["phase"] = TO_PARTNER
    else:
        visit["phase"] = TO_LEVEL
    return press_invest_once(task, PANEL_LEAVE)


def panel_belongs(visit, owner):
    """Say whether an upgrade panel is the one the visit stands at: the Combatant's before its Partner's."""
    return visit["phase"] in (TO_PROMOTE, TO_LEVEL) if owner == "combatant" else visit["phase"] == TO_PARTNER


def handle_daily_invest_promotion(task):
    """Promote the goal unit or its Partner once, only when the button equals `Promotions` over a met counter and the Units allow it.

    Any other caption, read whole or garbled, counts as short: it goes to the goal file and the panel is left.
    """
    if not invest_active(task):
        return False
    panel = invest.promotion_panel(task)
    if panel is None:
        return False
    signature = ("promotion", panel.owner, panel.level, panel.cap, panel.next, panel.have, panel.need, panel.cost, panel.caption)
    shown_for = invest_arrive(task, "panel", signature)
    inv = invest_state(task)
    visit = inv["visit"]
    if visit is None or visit["phase"] == VISITED or not visit["checked"] or not panel_belongs(visit, panel.owner):
        return press_invest_once(task, PANEL_LEAVE)
    if awaiting_spend(task, signature):
        return True
    action = invest.PROMOTION if panel.owner == "combatant" else invest.PARTNER_PROMOTION
    reason = invest.promotion_go(panel, inv["floor"])
    if panel.owner == "combatant":
        visit["below_cap"] = panel.level < panel.cap
        visit["units_short"] = invest.held_by_units(panel, reason)
    # A Promotion is made only where the visit opened the panel for it, so never right after levelling to a new cap.
    opened_for = visit["phase"] == TO_PROMOTE if panel.owner == "combatant" else visit["partner_action"] == invest.PARTNER_PROMOTION
    first = opened_for and action not in visit["read"] and not visit["spent"][action]
    if reason is None and first and action not in visit["no_effect"]:
        if shown_for < PANEL_SETTLE or guard_holds(task, signature):
            return True
        return spend(task, PROMOTE, panel.caption_box, action, signature, f"{panel.have}/{panel.need}, {amount(panel.cost)} of {amount(panel.units)} Units")
    if reason is not None:
        record_short(task, action, panel.have, panel.need, panel.cost, panel.caption_box, reason)
    return leave_panel(task, panel.owner, action)


def handle_daily_invest_level(task):
    """Level the goal unit or its Partner: Auto Register first, then `Level Up` while it gives levels, three presses a panel at most."""
    if not invest_active(task):
        return False
    panel = invest.level_panel(task)
    if panel is None:
        return False
    signature = ("level", panel.owner, panel.level, panel.gain, panel.cost, panel.caption)
    shown_for = invest_arrive(task, "panel", signature)
    inv = invest_state(task)
    visit = inv["visit"]
    if visit is None or visit["phase"] == VISITED or not visit["checked"] or not panel_belongs(visit, panel.owner):
        return press_invest_once(task, PANEL_LEAVE)
    if awaiting_spend(task, signature):
        return True
    action = invest.LEVEL if panel.owner == "combatant" else invest.PARTNER_LEVEL
    if panel.owner == "combatant":
        visit["phase"] = TO_LEVEL
    if action in visit["read"] or action in visit["no_effect"] or visit["spent"][action] >= LEVEL_CYCLES:
        return leave_panel(task, panel.owner, action)
    if level_held(task):
        note(task, f"{visit['unit']}: {action} left for a goal unit listed before it")
        return leave_panel(task, panel.owner, action)
    # Any other caption, as a tutorial line's `Space` over the panel, means the panel is not all there is.
    if panel.caption != invest.LEVEL_UP_WORD:
        note(task, f"{visit['unit']} {action}: the button reads {panel.caption_box.name.strip()!r}")
        return leave_panel(task, panel.owner, action)
    if panel.gain == 0:
        if visit["registered"] is None:
            visit["registered"] = time.monotonic()
            return press_invest(task, AUTO_REGISTER, panel.register_box)
        if time.monotonic() - visit["registered"] < REGISTER_WAIT:
            return True
    reason = invest.level_go(panel, inv["floor"])
    if reason is not None:
        note(task, f"{visit['unit']} {action}: {reason}")
        return leave_panel(task, panel.owner, action)
    if shown_for < PANEL_SETTLE or guard_holds(task, signature):
        return True
    visit["registered"] = None
    return spend(task, LEVEL_UP, panel.caption_box, action, signature, f"Lv.{panel.level}+{panel.gain}, {amount(panel.cost)} of {amount(panel.units)} Units")


def handle_daily_invest_map(task):
    """Open node 01 on every goal unit's Potential map and node 02 on the first goal unit's, then leave Details."""
    if not invest_active(task) or not invest.potential_map(task):
        return False
    signature = ("map", invest.only_match(task, invest.COUNTER, invest.NODE_02_COUNTER_REGION).group(0))
    invest_arrive(task, "map", signature)
    visit = invest_state(task)["visit"]
    if visit is None or visit["phase"] == VISITED:
        return press_invest_once(task, DETAILS_LEAVE)
    if not visit["checked"]:
        return tab_press(task, "stats", invest.STATS_TAB_REGION, STATS_TAB)
    if visit["phase"] != TO_POTENTIAL:
        return to_phase(task)
    waiting = opening_waits(task, signature, f"Potential node {visit['node']}")
    if waiting is None:
        return press_invest_once(task, DETAILS_LEAVE)
    if waiting:
        return True
    nodes = ("01", "02") if visit["index"] == 0 else ("01",)
    # Node 02 at its last level has nothing to buy and no button to read, so it is not opened.
    if "02" in nodes and "02" not in visit["nodes_done"] and invest.node_02_full(task):
        visit["nodes_done"].add("02")
        task.log_info(f"{visit['unit']}: Potential node 02 is at its last level")
    node = next((node for node in nodes if node not in visit["nodes_done"]), None)
    if node is None:
        end_visit(task)
        return press_invest_once(task, DETAILS_LEAVE)
    visit["node"] = node
    return guarded_press(task, NODE_01_ENTRY if node == "01" else NODE_02_ENTRY, None, signature)


def handle_daily_invest_node(task):
    """Activate the opened node while its button equals `Activate` over a met counter and the Units allow it: node 01 once, node 02 to the limit.

    A node panel with nothing left to buy, as an active node 01, counts the node as done.
    """
    if not invest_active(task):
        return False
    node = invest.node_panel(task)
    if node is None:
        done = invest.done_node(task)
        return done is not None and node_done(task, done)
    signature = ("node", node.name, node.level, node.have, node.need, node.cost, node.caption)
    shown_for = invest_arrive(task, "node", signature)
    inv = invest_state(task)
    visit = inv["visit"]
    if visit is None or visit["phase"] != TO_POTENTIAL or not visit["checked"] or visit["node"] is None:
        return press_invest_once(task, NODE_LEAVE)
    if awaiting_spend(task, signature):
        return True
    which = visit["node"]
    # The map opens only a node not done yet, so its panel showing again means the back arrow was not taken.
    if which in visit["nodes_done"]:
        return press_invest_once(task, NODE_LEAVE)
    action = invest.NODE_01 if which == "01" else invest.NODE_02
    if node.name != invest.NODE_NAMES[which] or (which == "02" and node.level is None):
        visit["nodes_done"].add(which)
        note(task, f"{visit['unit']}: Potential node {which} opened a panel that reads {node.name!r}")
        return press_invest_once(task, NODE_LEAVE)
    activated = visit["spent"][invest.NODE_01] + visit["spent"][invest.NODE_02]
    done = action in visit["no_effect"] or (which == "01" and visit["spent"][action]) or activated >= ACTIVATE_CAP
    if not done:
        reason = invest.node_go(node, inv["floor"])
        if reason is None:
            if shown_for < PANEL_SETTLE or guard_holds(task, signature):
                return True
            return spend(task, ACTIVATE, node.caption_box, action, signature, f"{node.have}/{node.need}, {amount(node.cost)} of {amount(node.units)} Units")
        record_short(task, action, node.have, node.need, node.cost, node.caption_box, reason)
    visit["nodes_done"].add(which)
    return press_invest_once(task, NODE_LEAVE)


def node_done(task, done):
    """Leave a node panel with nothing left to buy once it has read unchanged for `PANEL_SETTLE`, the node counting as done.

    The wait keeps a panel whose counter and button have not drawn yet from passing for one, and an awaited spend counts
    as done only after it: a single such reading frees the corner guard, and must not also end the spend's wait.
    """
    shown_for = invest_arrive(task, "node", ("node", done.name, "done"))
    inv = invest_state(task)
    visit = inv["visit"]
    if visit is None or visit["phase"] != TO_POTENTIAL or not visit["checked"] or visit["node"] is None:
        return press_invest_once(task, NODE_LEAVE)
    if shown_for < PANEL_SETTLE:
        return True
    if inv["spend"] is not None:
        took_effect(task)
    which = visit["node"]
    if which not in visit["nodes_done"]:
        if done.name != invest.NODE_NAMES[which]:
            note(task, f"{visit['unit']}: Potential node {which} opened a panel that reads {done.name!r}")
        else:
            task.log_info(f"{visit['unit']}: Potential node {which} has nothing left to buy")
    visit["nodes_done"].add(which)
    return press_invest_once(task, NODE_LEAVE)


def handle_daily_notice(task):
    """Close the Notice board."""
    if not on_notice(task):
        return False
    recognised(task)
    return press(task, NOTICE_CLOSE)


def handle_daily_banner(task):
    """Close the entry banner, told by its X and dots on a screen that is none of the others Daily knows."""
    if on_lobby(task) or on_menu(task) or on_notice(task):
        return False
    if find_icon(frame_of(task), BANNER_CLOSE_IMAGE, BANNER_MATCH, BANNER_CORNER) is None:
        return False
    recognised(task)
    return press(task, BANNER_CLOSE)


def handle_daily_lobby_menu(task):
    """Open the next chore from the menu, or close the menu once no chore in it is left.

    A chore whose entry is a caption is opened on the box OCR read; while that caption does not read, the menu counts as
    a screen Daily does not know.
    """
    if not on_menu(task):
        return False
    # The menu fading in over Details reads both, and a press made for either could land on the other.
    if invest.header(task) is not None:
        return handle_daily_unknown_screen(task)
    step = pending_step(task)
    entry = step.menu_entry if step is not None and step.menu_entry is not None else MENU_CLOSE
    caption = MENU_ENTRIES.get(entry)
    box = showing(task, caption) if caption is not None else None
    if caption is not None and box is None:
        return handle_daily_unknown_screen(task)
    recognised(task)
    return press(task, entry, box)


def handle_daily_lobby(task):
    """Start the next chore from the Lobby, or finish once every chore is done.

    The Carnival opens on its banner as OCR read it. A Lobby without the banner skips the chore, so the event ending
    needs no date: no spot is ever tapped where the banner used to be.
    """
    if not on_lobby(task):
        return False
    recognised(task)
    state = run_state(task)
    state["lobby_seen"] = time.monotonic()
    step = pending_step(task)
    if step is not None and step.name == "carnival":
        banner = showing(task, LOBBY_CARNIVAL)
        if banner is not None:
            return press(task, CARNIVAL_BANNER, banner)
        task.log_info("the Lobby shows no Nightmare Carnival banner, so its attendance is skipped")
        end_carnival(task, "Nightmare Carnival is not running")
        step = pending_step(task)
    if step is not None and step.name == INVEST:
        if invest_active(task) and not state["invest"]["ended"]:
            return press_invest(task, INVEST_ENTRY, showing(task, LOBBY_COMBATANTS))
        # Without a goal list the step leaves no trace, not even the goal file.
        state["steps"][INVEST] = DONE
        step = pending_step(task)
    if step is not None:
        return press(task, step.lobby_entry)
    settle_recount(task)
    mail = "mail claimed" if state["mail"] == "claimed" else "no mail to claim"
    invested = invest_summary(state["invest"])
    return stop(task, f"Daily finished: {mail}; {park_summary(state['park'])}; {claims_summary(state['claims'])}"
                      f"{'; ' + invested if invested else ''}.")


def handle_daily_faded_lobby(task):
    """Bring back the UI of a Lobby that has faded out.

    Only on the faded Lobby's own scene, since a screen that reads nothing or a single line could be anything else, as a
    popup still loading. Moments after a Lobby read, with a chore pending, it gets the Menu tap the Lobby would get, which
    brings the UI back or opens the menu. Without that read, as at a start on an idle Lobby, or with the Carnival's
    banner next, which only a read Lobby shows, it gets the wake tap on open sky.
    """
    if not reads_as_faded_lobby(task):
        return False
    if find_icon(frame_of(task), FADED_SCENE_IMAGE, FADED_SCENE_MATCH, FADED_SCENE_REGION, grey) is None:
        return False
    state = run_state(task)
    now = time.monotonic()
    seen = state["lobby_seen"]
    step = pending_step(task)
    if seen is not None and now - seen < FADED_SECONDS and step is not None and TARGETS[step.lobby_entry] is not None:
        recognised(task)
        return press(task, step.lobby_entry)
    recognised(task)
    woken = state["woken"]
    if woken is not None and now - woken < WAKE_WAIT:
        return True
    state["woken"] = now
    return press(task, WAKE)


def handle_daily_unknown_screen(task):
    """Take every frame no handler above knows, press nothing, and stop once that has lasted `UNKNOWN_SECONDS`.

    During the invest step it also drops the goal unit's name check: until the Stats tab reads the name again, nothing
    the visit owns is pressed.
    """
    state = run_state(task)
    visit = state["invest"]["visit"]
    if visit is not None:
        visit["checked"] = False
    now = time.monotonic()
    if state["unknown_since"] is None:
        state["unknown_since"] = now
    if now - state["unknown_since"] < UNKNOWN_SECONDS:
        return True
    return stop(task, f"Stopped: Daily does not know this screen and pressed nothing for {UNKNOWN_SECONDS}s. Go back to the Lobby, then press Start again.")


# The run loop takes the first handler returning True. `remote` puts its handler first and `stuck_stop` its stop ahead
# of the Rescue stop. Overlays come before what they cover, the banner's weak check after every text check, and the Lobby
# last of the known screens, so a popup is never taken for a clean Lobby. The park's dialogs and stories come before the
# panels under them, its panels before the park view drawn beside them, and Dream Park's and The Path of a Captain's
# pages before the Event list they sit in. The invest step's result cards come before the panels they cover, its panels
# before the Details tabs under them. None of upstream's generic handlers is here: its Lobby stop would end Daily on its first frame, and its blind
# taps and centred Confirm press what Daily never reads.
PAGE_HANDLERS = [
    handle_rescue_screen,
    handle_daily_tutorial,
    handle_daily_overtime,
    handle_daily_items_obtained,
    handle_daily_attendance,
    handle_daily_mail,
    handle_daily_activity,
    handle_daily_achievement_category,
    handle_daily_achievement_cards,
    handle_daily_carnival,
    handle_daily_rules_dialog,
    handle_daily_profit_report,
    handle_daily_skip_dialog,
    handle_daily_park_story,
    handle_daily_rank_result,
    handle_daily_rank_screen,
    handle_daily_manage_panel,
    handle_daily_facilities,
    handle_daily_skill_tab,
    handle_daily_park_view,
    handle_daily_park_achievements,
    handle_daily_event_page,
    handle_daily_captain_page,
    handle_daily_event_list,
    handle_daily_invest_card,
    handle_daily_invest_promotion,
    handle_daily_invest_level,
    handle_daily_invest_node,
    handle_daily_invest_stats,
    handle_daily_invest_partners,
    handle_daily_invest_map,
    handle_daily_invest_list,
    handle_daily_notice,
    handle_daily_banner,
    handle_daily_lobby_menu,
    handle_daily_lobby,
    handle_daily_faded_lobby,
    handle_daily_unknown_screen,
]


class DailyMode(TriggerTask):
    """Claims the day's free rewards from the Lobby, visits Dream Park, invests in the goal Combatants, and stops on the Lobby."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "Daily"
        self.description = ("Start on the Lobby. Closes the entry popups, claims the daily attendance reward, all mail, the ready Activity rewards "
                            "(Growth Guide, daily and weekly schedules, Achievement Log), the ready achievements and, while the Nightmare "
                            "Carnival runs, its pending attendance days. Then opens the Event list, claims each reached tier of The Path of "
                            "a Captain and visits Nightmare Dream Park while it runs: ranks it up, builds and upgrades rides, buys its AI "
                            "Automation and Another Happy Day skills with the park's own profit and claims its achievements. "
                            "Last, with Goal Combatants set, promotes and levels them and their Partners and unlocks Potential "
                            "nodes from materials already owned. Stops on the Lobby. Presses nothing else.")
        self.trigger_interval = 1
        self.all_texts = []
        self.default_config['_enabled'] = False
        self.default_config[GOALS_SETTING] = []
        self.config_type[GOALS_SETTING] = {"type": "drop_down", "options_available": COMBATANTS}
        self.config_description[GOALS_SETTING] = (
            "Combatants to invest in, the first listed first. After the chores, each gets its Promotion, Level Up to the cap, its Partner's "
            "Promotion and Level Up and Potential node 01, and the first also node 02, spending only materials and Units "
            "already owned. Empty skips the step.")
        self.default_config[FLOOR_SETTING] = UNITS_FLOOR
        self.config_type[FLOOR_SETTING] = {"min": 0}
        self.config_description[FLOOR_SETTING] = "Never spend Units below this many."

    def enable(self):
        """Stop any other mode, and start the run afresh."""
        stop_others(self, OTHER_MODES)
        vars(self).pop(RUN, None)
        run_state(self)
        super().enable()

    def disable(self):
        """Stop, forgetting the run."""
        vars(self).pop(RUN, None)
        super().disable()

    def run(self):
        """Read the screen once and hand it to the first handler that knows it."""
        utils = loaded("utils")
        texts = self.ocr()
        self.all_texts = utils._simplify_texts(texts) if utils is not None else texts
        for handle_page in PAGE_HANDLERS:
            if handle_page(self):
                return


def stop_others(task, class_names):
    """Stop the named modes if they are running.

    Args:
        task: The mode about to start, for its executor.
        class_names: The class names of the modes to stop.
    """
    for name in class_names:
        other = task.executor.get_task_by_class_name(name)
        if other is not None and other is not task and other.enabled:
            other.disable()


def stopping_daily(original_enable, task):
    """Wrap another mode's `enable` so starting it stops Daily first.

    Args:
        original_enable: The mode's own `enable`.
        task: The mode being wrapped.

    Returns:
        The replacement `enable`.
    """
    def enable():
        stop_others(task, (DailyMode.__name__,))
        original_enable()

    return enable


def teaching_modes(original_load_config):
    """Wrap `BaseTask.load_config` so the other modes stop Daily when they start.

    Wrapping here puts it ahead of the run loop and the debug port, which both take their reference to `enable` later.

    Args:
        original_load_config: The unbound `load_config` being replaced.

    Returns:
        The replacement.
    """
    def load_config(self):
        if type(self).__name__ in OTHER_MODES:
            self.enable = stopping_daily(self.enable, self)
        original_load_config(self)

    return load_config


def apply():
    """Have Chaos, Sortie and Story stop Daily when they start."""
    global _patched
    if _patched:
        return
    try:
        from ok.task.task import BaseTask
    except ImportError:
        logger.warning("could not import BaseTask, starting another mode will not stop Daily")
        _patched = True
        return
    BaseTask.load_config = teaching_modes(BaseTask.load_config)
    _patched = True
