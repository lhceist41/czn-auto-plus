"""Check Daily's visit to Nightmare Dream Park: what it reads off the park's screens and what it presses.

The screens are the boxes OCR read off the Global client's park, as the bot sees them once the catalog has mapped them,
and the colour tests run on crops of the same captures. What the visit must never do: press a row whose price does not
read as a plain park number, go on after a price reading as Crystals or money, press a ride twice without its level
rising, press the grey Rank Up left on the next card, press Rules of Good Order's 确认, or stop Daily when the event is
gone.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

from src.en import daily, dream_park  # noqa: E402
from tests.fakes import HEIGHT, WIDTH  # noqa: E402
from tests.TestDailyMode import EVENT_LIST, EVENT_LIST_WITHOUT_PARK, ITEMS, LOBBY, MENU, NEAR, POINTS, Daily, Task, placed, run_pass  # noqa: E402

# Dream Park's event page, opened from the Event list.
PAGE = (
    ('△', 0.041, 0.046), ('Event', 0.109, 0.047), ('-', 0.977, 0.021), ('↓ Recommended Events', 0.091, 0.137), ('N', 0.214, 0.111),
    ('Nightmare Dream Park', 0.814, 0.167), ('Event Description', 0.821, 0.230), ('31d 2h', 0.938, 0.231),
    ('n to a New Journey', 0.099, 0.270), ('To celebrate the Nightmare Carnival, a theme park has opened', 0.756, 0.284),
    ("Captain, let's build a'land of dreams together!", 0.822, 0.353), ('aboard the Ss Nightmare.', 0.886, 0.318),
    ('kie Captain Mission', 0.101, 0.394), ("VAportion ofth Dream Park' revenue il be used to sgpthort", 0.728, 0.387),
    ('underprivileged children.', 0.889, 0.422), ('le Path of a Captain', 0.101, 0.516), ('N', 0.202, 0.577), ('φ', 0.021, 0.615),
    ('Nightmare Dream Park', 0.111, 0.643), ('A', 0.856, 0.634), ('1st Anniversary Limited Reward', 0.806, 0.722),
    ('lise Upon the Snow', 0.099, 0.770), ('New Event! [Rules of Good Order]', 0.803, 0.803), ('ed Against the Cycle', 0.102, 0.893),
    ('Achievements', 0.551, 0.900), ('Enter Amusement Park', 0.775, 0.901), ('XN', 0.151, 0.949),
)
# The park view on entry, Rank 5, with no panel open.
PARK_VIEW = (
    ('5', 0.097, 0.047), ('The Amusement Park All the Buzz Is About', 0.316, 0.048), ('84.38K', 0.956, 0.047),
    ('Rules of Gooal', 0.165, 0.132), ('N', 0.212, 0.122), ('Order', 0.190, 0.168), ('0/54', 0.170, 0.205), ('Manage', 0.087, 0.294),
    ('Recruit', 0.084, 0.382), ('Operate', 0.088, 0.473), ('★', 0.699, 0.639), ('肉', 0.701, 0.746),
)
# Facilities at Rank 5, opened at the top of the list: Thrill 61, Comfort 34, Happiness 29 of 36. Top Spin's button is cut off.
FACILITIES = (
    ('5', 0.097, 0.046), ('The Amusement Park All the Buzz Is About', 0.316, 0.046), ('99.21K', 0.956, 0.046),
    ('Rules of Gooal', 0.165, 0.132), ('N', 0.212, 0.122), ('61/36', 0.705, 0.106), ('34/36', 0.794, 0.105), ('29/36', 0.929, 0.106),
    ('0/54', 0.170, 0.204), ('Order', 0.189, 0.167), ('i', 0.033, 0.295), ('Manage', 0.087, 0.293), ('Facilities', 0.803, 0.274),
    ('Recruit', 0.085, 0.382), ('o Merry-Go-Round', 0.782, 0.350), ('Lv.34/50', 0.934, 0.349), ('😎', 0.741, 0.402),
    ('Comfort +34', 0.789, 0.402), ('+41/6s', 0.882, 0.400), ('六', 0.033, 0.479), ('Operate', 0.087, 0.473), ('强化', 0.772, 0.456),
    ('4.65K', 0.947, 0.454), ('o Tagada', 0.752, 0.530), ('Lv.29/50', 0.933, 0.527), ('Happiness +29', 0.795, 0.580),
    ('+23/4s', 0.885, 0.579), ('强化', 0.772, 0.634), ('6.37K', 0.946, 0.632), ('o Roller Coaster', 0.772, 0.706), ('Lv.25/50', 0.933, 0.706),
    ('Thrill +25', 0.779, 0.756), ('+40/5s', 0.882, 0.757), ('强化', 0.773, 0.812), ('3.07K', 0.946, 0.810), ('o Top Spin', 0.755, 0.885),
    ('Lv.18/50', 0.934, 0.883), ('Press and hold the button to upgrade quickly.', 0.802, 0.930),
)
# The same list after nine upgrades: Comfort and Happiness at 36 of 36.
FACILITIES_DONE = (
    ('5', 0.097, 0.047), ('The Amusement Park All the Buzz Is About', 0.315, 0.046), ('10.82K', 0.957, 0.046),
    ('Rules of Gooal', 0.165, 0.132), ('N', 0.212, 0.122), ('61/36', 0.707, 0.105), ('36/36', 0.803, 0.105), ('36 /36', 0.928, 0.106),
    ('0/54', 0.171, 0.204), ('Order', 0.189, 0.167), ('6', 0.032, 0.294), ('Manage', 0.087, 0.294), ('Facilities', 0.803, 0.274),
    ('Recruit', 0.085, 0.382), ('o Merry-Go-Round', 0.782, 0.350), ('Lv.36/50', 0.934, 0.349), ('😎', 0.741, 0.402),
    ('Comfort +36', 0.789, 0.402), ('+43/6s', 0.893, 0.400), ('六', 0.033, 0.479), ('Operate', 0.087, 0.473), ('强化', 0.772, 0.456),
    ('6.69K', 0.946, 0.454), ('o Tagada', 0.752, 0.530), ('Lv.36/50', 0.934, 0.529), ('😊', 0.740, 0.579), ('Happiness +36', 0.796, 0.580),
    ('+29/4s', 0.885, 0.579), ('强化', 0.772, 0.634), ('22.81K', 0.942, 0.632), ('o Roller Coaster', 0.772, 0.706),
    ('Lv.25/50', 0.933, 0.706), ('Thrill +25', 0.779, 0.756), ('+40/5s', 0.883, 0.757), ('强化', 0.773, 0.812), ('3.07K', 0.946, 0.810),
    ('o Top Spin', 0.755, 0.885), ('Lv.18/50', 0.934, 0.883), ('Press and hold the button to upgrade quickly.', 0.802, 0.930),
)
# Rank 6, after two more upgrades: Comfort 38 and Happiness 36 of 43, profit 5.67K.
FACILITIES_RANK7 = (
    ('6', 0.098, 0.046), ('The Amusement Park All the Buzz Is About', 0.316, 0.046), ('5.67K', 0.959, 0.046),
    ('Rules of Gooal', 0.165, 0.132), ('N', 0.212, 0.122), ('61/43', 0.700, 0.106), ('38/43', 0.796, 0.105), ('36/43', 0.929, 0.106),
    ('0/54', 0.171, 0.204), ('Order', 0.189, 0.167), ('Manage', 0.087, 0.294), ('Facilities', 0.803, 0.274), ('Recruit', 0.084, 0.382),
    ('o Merry-Go-Round', 0.782, 0.350), ('Lv.38/50', 0.934, 0.349), ('😎', 0.741, 0.402), ('Comfort +38', 0.787, 0.402),
    ('+46/6s', 0.893, 0.400), ('-', 0.047, 0.444), ('六', 0.033, 0.479), ('Operate', 0.087, 0.473), ('强化', 0.772, 0.456),
    ('9.63K', 0.947, 0.454), ('o Tagada', 0.752, 0.530), ('Lv.36/50', 0.934, 0.529), ('Happiness +36', 0.796, 0.580),
    ('+29/4s', 0.885, 0.579), ('强化', 0.772, 0.634), ('22.81K', 0.942, 0.632), ('o Roller Coaster', 0.772, 0.706),
    ('Lv.25/50', 0.933, 0.706), ('Thrill +25', 0.779, 0.756), ('+40/5s', 0.883, 0.757), ('强化', 0.773, 0.812), ('3.07K', 0.946, 0.810),
    ('o Top Spin', 0.755, 0.885), ('Lv.18/50', 0.934, 0.883), ('Press and hold the button to upgrade quickly.', 0.803, 0.931),
)
# The list after one long drag flung it seven rows down: only locked rides.
FACILITIES_FLUNG = (
    ('5', 0.097, 0.046), ('The Amusement Park All the Buzz Is About', 0.316, 0.046), ('87.92K', 0.955, 0.046),
    ('Rules of Gooal', 0.165, 0.132), ('N', 0.211, 0.122), ('61/3634/3629/36', 0.808, 0.106), ('0/54', 0.172, 0.204),
    ('Order', 0.190, 0.168), ('Manage', 0.087, 0.293), ('Facilities', 0.803, 0.274), ('Recruit', 0.084, 0.382),
    ('o Haunted House', 0.777, 0.347), ('Thrill +0', 0.776, 0.398), ('+0/5s', 0.890, 0.399), ('六', 0.033, 0.479), ('Operate', 0.086, 0.471),
    ('Reach Amusement Park Rank 12', 0.852, 0.452), ('o Observatory', 0.767, 0.525), ('Happiness +0', 0.791, 0.575),
    ('+0/6s', 0.880, 0.576), ('Reach Amusement Park Rank 15', 0.852, 0.631), ('o Swing Boat', 0.764, 0.702), ('Thrill +0', 0.776, 0.754),
    ('+0/5s', 0.879, 0.754), ('Reach Amusement Park Rank 17', 0.850, 0.807), ('o Bumper Cars', 0.769, 0.881),
    ('Press and hold the button to upgrade quickly.', 0.802, 0.931),
)
# The Manage panel at Rank 5 with every emotion at its target.
MANAGE = (
    ('5', 0.097, 0.047), ('The Amusement Park All the Buzz Is About', 0.316, 0.046), ('11.97K', 0.957, 0.046),
    ('Rules of Gooal', 0.165, 0.132), ('N', 0.212, 0.122), ('Order', 0.190, 0.168), ('Manage', 0.803, 0.139), ('0/54', 0.171, 0.203),
    ('6', 0.032, 0.294), ('Manage', 0.085, 0.294), ('The Amusement Park All the Buzz Is About Rank 5', 0.804, 0.313),
    ('Recruit', 0.084, 0.383), ('o Profit Status', 0.691, 0.398), ('91/s', 0.936, 0.397), ('六', 0.033, 0.481), ('Operate', 0.088, 0.472),
    ('o Total Profit', 0.687, 0.453), ('242.55K', 0.926, 0.452), ('o Max Simultaneous Visitors', 0.741, 0.508), ('3', 0.953, 0.509),
    ('oMax Idle Time', 0.696, 0.563), ('7h 30m', 0.929, 0.562), ('o Visitor Emotions', 0.705, 0.633), ('Thrill', 0.705, 0.674),
    ('61/36', 0.936, 0.675), ('Comfort', 0.716, 0.744), ('36 /36', 0.935, 0.744), ('Happiness', 0.722, 0.811), ('36 /36', 0.935, 0.809),
    ('Amusement Park Rank', 0.804, 0.906),
)
# The Manage panel just after the rank up to Rank 6: targets 43.
MANAGE_RANK6 = (
    ('6', 0.097, 0.047), ('The Amusement Park All the Buzz Is About', 0.316, 0.047), ('17.44K', 0.957, 0.045),
    ('Rules of Gooal', 0.165, 0.132), ('N', 0.212, 0.122), ('Order', 0.190, 0.168), ('Manage', 0.803, 0.139), ('0/54', 0.171, 0.204),
    ('0', 0.033, 0.294), ('Manage', 0.085, 0.293), ('The Amusement Park All the Buzz Is About Rank 6', 0.805, 0.313),
    ('Recruit', 0.084, 0.383), ('o Profit Status', 0.691, 0.398), ('91/s', 0.936, 0.397), ('Operate', 0.087, 0.473),
    ('o Total Profit', 0.687, 0.454), ('248.01K', 0.926, 0.452), ('o Max Simultaneous Visitors', 0.741, 0.509), ('3', 0.953, 0.509),
    ('o Max Idle Time', 0.696, 0.564), ('7h 40m', 0.929, 0.563), ('o Visitor Emotions', 0.705, 0.633), ('Thril', 0.706, 0.675),
    ('61/43', 0.936, 0.676), ('Comfort', 0.716, 0.744), ('36 /43', 0.935, 0.744), ('8', 0.185, 0.826), ('Happiness', 0.722, 0.811),
    ('36/43', 0.935, 0.810), ('Amusement Park Rank', 0.804, 0.906),
)
# The Amusement Park Rank screen at Rank 5 with Rank 6 earned: Rank Up on the Rank 6 card.
RANK_READY = (
    ('5', 0.096, 0.045), ('The Amusement Park All the Buzz Is About', 0.316, 0.046), ('12.56K', 0.957, 0.046),
    ('Amusement Park Rank', 0.500, 0.136), ('ent Park All the Buzz Is About★★★★★★★★', 0.201, 0.256), ('★', 0.840, 0.248),
    ('The S', 0.963, 0.257), ('RANK5', 0.175, 0.348), ('RANK6', 0.427, 0.349), ('RANK7', 0.675, 0.345), ('RANK8', 0.950, 0.348),
    ('oObjective', 0.178, 0.408), ('oObjective', 0.430, 0.408), ('oObjective', 0.682, 0.408), ('oObjectiv', 0.949, 0.409),
    ('21/21', 0.078, 0.463), ('·Thrill', 0.180, 0.463), ('29/29', 0.328, 0.463), ('·Thrilll', 0.432, 0.463), ('36/36', 0.579, 0.463),
    ('·Thril', 0.683, 0.463), ('43/43', 0.831, 0.463), ('·Thril', 0.954, 0.463), ('21/21', 0.078, 0.514), ('· Comfort', 0.191, 0.513),
    ('29/29', 0.328, 0.513), ('Comfort', 0.446, 0.511), ('36/36', 0.579, 0.511), ('·Comfort', 0.693, 0.513), ('36/43', 0.831, 0.513),
    ('·@cComf', 0.955, 0.512), ('21/21', 0.078, 0.564), ('· Happiness', 0.198, 0.564), ('29/29', 0.328, 0.563), ('•', 0.415, 0.565),
    ('Happiness', 0.463, 0.562), ('36/36', 0.580, 0.564), ('· Happiness', 0.701, 0.564), ('36/43', 0.831, 0.564), ('• Happ', 0.956, 0.565),
    ('o Rank Up Benefits', 0.205, 0.624), ('o Rank Up Benefits', 0.457, 0.624), ('o Rank Up Benefits', 0.708, 0.624),
    ('o Rank Up', 0.949, 0.625), ('as] can be', 0.051, 0.707), ('10 min', 0.037, 0.678), ('· Max Offline Time + 10 min', 0.228, 0.679),
    ('rs', 0.024, 0.739), ('·[Drop Tower] unlocked', 0.222, 0.707), ('· Max Offline Time + 10 min', 0.479, 0.678),
    ('· Max Offline Time + 10 min', 0.731, 0.679), ('·[Another Happy Day] Skill', 0.732, 0.738),
    ('·[Social Etiquette] Skill unlocked', 0.751, 0.707), ('· Max mané', 0.955, 0.708), ('· Max Offir', 0.956, 0.679),
    ('unlocked', 0.679, 0.768), ('·[Special G', 0.957, 0.737), ('can be assi', 0.954, 0.797), ('·[Sereniel]', 0.956, 0.767),
    ('Complete', 0.051, 0.901), ('Achievement Complete', 0.252, 0.900), ('Rank Up', 0.502, 0.900), ('New', 0.971, 0.861),
)
# The Rank 6 result.
RANK_RESULT = (
    ('ark All the Buzz ls About', 0.399, 0.048), ('14.04K', 0.957, 0.046), ('★★★', 0.049, 0.255), ('ててて', 0.097, 0.256),
    ("The SS Nightmare's Most Popular", 0.818, 0.258), ('Spo1', 0.966, 0.262), ('RANK', 0.170, 0.346), ('6', 0.199, 0.351),
    ('ANK8', 0.707, 0.346), ('The Amusement Park All the Buzz Is About', 0.502, 0.411), ('★★★★★', 0.516, 0.444),
    ('Rank 6 Achieved', 0.500, 0.521), ('• Max Offline Time + 10 min', 0.502, 0.660), ('New Story Available', 0.773, 0.860),
    ('Complete', 0.051, 0.901), ('Achievement Complete', 0.252, 0.901), ('点击屏幕关闭窗口', 0.500, 0.938),
)
# The Rank screen after the rank up: Rank Up still drawn, on the next card, grey.
RANK_AFTER = (
    ('6', 0.097, 0.045), ('The Amusement Park All the Buzz Is About', 0.316, 0.046), ('15.16K', 0.957, 0.046),
    ('Amusement Park Rank', 0.501, 0.137), ('★★★★★★★', 0.078, 0.256), ("'The SS Nightmare's Most Popular Spot", 0.836, 0.257),
    ('RANK6', 0.174, 0.347), ('RANK7', 0.426, 0.344), ('RANK8', 0.699, 0.348), ('RANK 9', 0.949, 0.347), ('oObjective', 0.179, 0.407),
    ('oObjective', 0.430, 0.407), ('。Objective', 0.702, 0.408), ('。Objectiv', 0.950, 0.410), ('29/29', 0.077, 0.463),
    ('·Thril', 0.180, 0.462), ('36/36', 0.328, 0.463), ('·Thril', 0.431, 0.463), ('43 /43', 0.580, 0.464), ('·Thril', 0.703, 0.463),
    ('50/50', 0.852, 0.464), ('·Thril', 0.955, 0.464), ('29/29', 0.076, 0.511), ('·Comfort', 0.191, 0.513), ('36/36', 0.328, 0.513),
    ('Comfort', 0.446, 0.513), ('36/43', 0.580, 0.514), ('· Comfort', 0.714, 0.513), ('36/50', 0.851, 0.511), ('·@comf', 0.956, 0.513),
    ('29/29', 0.077, 0.564), ('· Happiness', 0.198, 0.564), ('36/36', 0.328, 0.564), ('•', 0.416, 0.564), ('Happiness', 0.463, 0.563),
    ('36/43', 0.580, 0.564), ('· Happiness', 0.721, 0.564), ('36/50', 0.852, 0.562), ('• Happ', 0.956, 0.564),
    ('o Rank Up Benefits', 0.205, 0.624), ('o Rank Up Benefits', 0.457, 0.624), ('o Rank Up Benefits', 0.729, 0.624),
    ('o Rank Up', 0.949, 0.624), ('10 min', 0.036, 0.677), (';ked', 0.030, 0.707), ('• Max Offline Time +10 min', 0.228, 0.679),
    ('• Max Offline Time + 10 min', 0.479, 0.679), ('·[Social Etiquette] Skill unlocked', 0.499, 0.706),
    ('· Max Offline Time + 10 min', 0.751, 0.679), ('• Max manager count +1', 0.744, 0.708), ('· Max Offir', 0.955, 0.678),
    ('·[Another Happy Day] Skil', 0.480, 0.736), ('unlocked', 0.427, 0.768), ('[Sereniel], [Cassius], [Maribell]', 0.769, 0.766),
    ('[Special Guest] unlocked', 0.752, 0.737), ('can be assigned as managers', 0.759, 0.798), ('New Story Available', 0.773, 0.860),
    ('Complete', 0.051, 0.901), ('Achievement Complete', 0.252, 0.900), ('Rank Up', 0.503, 0.902), ('……', 0.774, 0.899),
)
# The event's achievements, Chronicles tab, nothing ready.
CHRONICLES = (
    ('Event Special Rewards', 0.185, 0.045), ('N', 0.973, 0.030), ('5', 0.020, 0.163), ('musement Park Chr', 0.097, 0.144),
    ("Achieve [The SS Nightmare's Most Popular Spot]", 0.359, 0.130), ('1/7', 0.046, 0.179), ('0/1', 0.219, 0.202),
    ('00 110+', 0.717, 0.166), ('30', 0.601, 0.200), ('musement Park Mar', 0.097, 0.253), ('0/16', 0.051, 0.292),
    ('Achieve [The Rising Star of the Amusement Park', 0.358, 0.285), ('Event Special Rewards', 0.882, 0.265), ('0/1', 0.219, 0.355),
    ('World]', 0.226, 0.316), ('1|10++', 0.718, 0.319), ('30', 0.599, 0.354),
    ('Achieve [The Superstar of the Amusement Park', 0.355, 0.437), ('0/1', 0.220, 0.507), ('World]', 0.226, 0.469), ('0110', 0.718, 0.471),
    ('Line]', 0.219, 0.623), ('Achieve [An Amusement Park With a Never-Ending', 0.367, 0.590), ('0/1', 0.219, 0.660),
    ('0110', 0.718, 0.624), ('30', 0.600, 0.657), ('Progress', 0.828, 0.680), ('117', 0.952, 0.678), ('0/1', 0.219, 0.812),
    ('Happiness]', 0.239, 0.775), ('Achieve [An Amusement Park That Brings', 0.338, 0.744), ('31d remaining', 0.910, 0.737),
    ('0+110', 0.718, 0.777), ('30', 0.600, 0.810), ('Achieve [An Amusement Park That Shines Like a', 0.359, 0.895),
    ('Not achieved', 0.882, 0.863), ('Sunernoval', 0.241, 0.925),
)
# Chronicles scrolled to its end: the claimed Rank 4 row last, greyed, with no `Claimed` text, only `1/1`.
CHRONICLES_SCROLLED = (
    ('Event Special Rewards', 0.184, 0.045), ('N', 0.973, 0.030), ('WVUIIUJ', 0.226, 0.095), ('Amusement Park', 0.104, 0.142),
    ('0/1', 0.220, 0.130), ('30', 0.599, 0.128), ('1/7', 0.046, 0.180), ('World]', 0.226, 0.244),
    ('Achieve [The Superstar of the Amusement Park', 0.356, 0.212), ('ent', 0.045, 0.256), ('Amusementl', 0.120, 0.255),
    ('0/16', 0.050, 0.292), ('0/1', 0.220, 0.283), ('00 110+', 0.717, 0.246), ('30', 0.601, 0.280), ('Event Special Rewards', 0.883, 0.265),
    ('Achieve [An Amusement Park With a Never-Ending', 0.366, 0.365), ('0/1', 0.219, 0.436), ('Line]', 0.219, 0.396),
    ('110.', 0.717, 0.400), ('30', 0.601, 0.435), ('Achieve [An Amusement Park That Brings', 0.337, 0.519), ('0/1', 0.219, 0.588),
    ('Happiness]', 0.239, 0.550), ('++1|10', 0.717, 0.551), ('30', 0.600, 0.585),
    ('Achieve [An Amusement Park That Shines Like a', 0.359, 0.671), ('0/1', 0.219, 0.741), ('Supernova]', 0.241, 0.702),
    ('Progress', 0.828, 0.680), ('117', 0.951, 0.678), ('30', 0.601, 0.740), ('31d remaining', 0.910, 0.737),
    ('Achieve [The Amusement Park All the Buzz Is About]', 0.372, 0.824), ('1/1', 0.219, 0.894), ('Not achieved', 0.882, 0.863),
    ('30', 0.600, 0.893),
)
# The Management tab, nothing ready.
MANAGEMENT = (
    ('Event Special Rewards', 0.185, 0.045), ('N', 0.973, 0.030), ('Iusement Park Chro', 0.098, 0.142),
    ('Reach [Merry-Go-Round] Level 50', 0.314, 0.131), ('0', 0.658, 0.137), ('1/7', 0.046, 0.181), ('34/ 50', 0.228, 0.201),
    ('10', 0.598, 0.198), ('3', 0.662, 0.200), ('の', 0.019, 0.273), ('iusement Park Man:', 0.098, 0.253), ('0/16', 0.050, 0.292),
    ('Reach [Tagada] Level 50', 0.283, 0.285), ('0', 0.658, 0.291), ('Event Special Rewards', 0.882, 0.265), ('0+0110', 0.718, 0.318),
    ('29/ 50', 0.228, 0.356), ('10', 0.601, 0.352), ('3', 0.665, 0.355), ('Reach [Roller Coaster] Level 50', 0.304, 0.437),
    ('0', 0.657, 0.443), ('25/50', 0.228, 0.507), ('0110', 0.717, 0.470), ('10', 0.601, 0.506), ('2', 0.663, 0.506),
    ('Reach [Top Spin] Level 50', 0.287, 0.589), ('0', 0.659, 0.595), ('011', 0.717, 0.623), ('18/ 50', 0.228, 0.661), ('10', 0.598, 0.659),
    ('3', 0.663, 0.658), ('Progress', 0.828, 0.680), ('117', 0.952, 0.678), ('Reach [Drop Tower] Level 50', 0.297, 0.743),
    ('0', 0.657, 0.748), ('00110+', 0.718, 0.776), ('31d remaining', 0.910, 0.737), ('0/50', 0.224, 0.813), ('10', 0.599, 0.810),
    ('Reach [Special Guest] Level 50', 0.302, 0.895), ('Not achieved', 0.882, 0.863), ('C', 0.658, 0.902), ('.o1l1o.', 0.720, 0.928),
)
# 1363, the Rank screen at Rank 1 with nothing earned: Rank Up drawn grey on the Rank 2 card.
RANK_UNEARNED = (
    ('1', 0.099, 0.046), ('One Step at a Time', 0.208, 0.046), ('国', 0.878, 0.043), ('5.11K', 0.962, 0.046),
    ('Amusement Park Rank', 0.501, 0.137), ("'One Step ata Time★★★★★★★★", 0.207, 0.256),
    ('*The Amusement Park All the Buzz Is About ★★★→', 0.783, 0.256), ('RANK2', 0.076, 0.349), ('RANK 3', 0.323, 0.347),
    ('RANK 4', 0.599, 0.346), ('RANK5', 0.849, 0.347), ('oObjective', 0.078, 0.408), ('。Objective', 0.330, 0.408),
    ('。Objective', 0.602, 0.408), ('oObjective', 0.853, 0.407), ('·Thrill', 0.080, 0.463), ('017', 0.238, 0.464),
    ('·Thrilll', 0.332, 0.463), ('·Comfort', 0.342, 0.511), ('0/14', 0.485, 0.463), ('·Thril', 0.603, 0.463), ('117', 0.239, 0.513),
    ('1/14', 0.486, 0.512), ('0/21', 0.757, 0.463), ('1/21', 0.757, 0.512), ('·Thril', 0.856, 0.462), ('·Comfort', 0.091, 0.513),
    ('· Comfort', 0.614, 0.513), ('·Comfort', 0.866, 0.513), ('· Happiness', 0.101, 0.564), ('017', 0.238, 0.564), ('•', 0.315, 0.564),
    ('Happiness', 0.363, 0.564), ('0/14', 0.485, 0.563), ('· Happiness', 0.621, 0.564), ('0/21', 0.756, 0.563),
    ('· Happiness', 0.876, 0.564), ('o Rank Up Benefits', 0.105, 0.624), ('o Rank Up Benefits', 0.357, 0.624),
    ('o Rank Up Benefits', 0.629, 0.624), ('o Rank Up Benefits', 0.880, 0.624), ('· Max Offline Time + 10 min', 0.128, 0.677),
    ('· Max manager count +1', 0.371, 0.706), ('· Max Offline Time + 10 min', 0.379, 0.679),
    ('·[Luke], [Beryl], [Lucas] can be', 0.665, 0.706), ('· Max Offline Time + 10 min', 0.652, 0.679),
    ('· Max Offline Time + 10 min', 0.904, 0.678), ('·[Top Spin]unlocked', 0.364, 0.738), ('assigned as managers', 0.637, 0.739),
    ('·[Drop Tower] unlocked', 0.897, 0.708), ('New Story Available', 0.673, 0.860), ('Rank Up', 0.152, 0.902),
)
# 1365, the Rules of Good Order dialog over the Manage panel.
RULES = (
    ('1One Step at a Time', 0.192, 0.046), ('6.02K', 0.960, 0.047), ("Rules of Gooa'", 0.165, 0.133), ('N', 0.211, 0.122),
    ('Order', 0.190, 0.167), ('Manage', 0.803, 0.138), ('0/54', 0.171, 0.204), ('Mana', 0.078, 0.290),
    ('This event takes place after reaching the highest Rank in Dream Park.', 0.502, 0.423),
    ('Would you like to view it now?', 0.502, 0.463), ('取消', 0.347, 0.631), ('进入', 0.536, 0.594), ('确认', 0.667, 0.631),
    ('Comfort', 0.715, 0.743), ('Happiness', 0.722, 0.810), ('0', 0.936, 0.809), ('Amusement Park Rank', 0.803, 0.906),
)
# 1373, Facilities at Rank 1: the header reads as `8177 17` and `217`.
FACILITIES_RANK1 = (
    ('One Step at a Time', 0.208, 0.046), ('9.82K', 0.960, 0.047), ('Rules of Gooal', 0.165, 0.132), ('N', 0.212, 0.122),
    ('8177 17', 0.784, 0.106), ('217', 0.923, 0.106), ('0/54', 0.171, 0.204), ('Order', 0.189, 0.167), ('へ', 0.714, 0.195),
    ('」', 0.033, 0.297), ('Manage', 0.087, 0.294), ('Facilities', 0.802, 0.272), ('Recruit', 0.085, 0.382),
    ('0 Merry-Go-Round', 0.782, 0.351), ('Lv.7/50', 0.929, 0.350), ('Comfort +7', 0.784, 0.402), ('+8/6s', 0.891, 0.403),
    ('Operate', 0.085, 0.473), ('强化', 0.772, 0.456), ('34', 0.956, 0.454), ('o Tagada', 0.752, 0.530), ('LV.2/50', 0.930, 0.530),
    ('Happiness +2', 0.792, 0.580), ('+2/4s', 0.883, 0.579), ('强化', 0.772, 0.634), ('24', 0.956, 0.631), ('o Roller Coaster', 0.772, 0.706),
    ('LV.8/50', 0.930, 0.706), ('Thrill +8', 0.776, 0.757), ('+13/5s', 0.884, 0.758), ('强化', 0.772, 0.812), ('69', 0.957, 0.810),
    ('o Top Spin', 0.755, 0.885), ('Press and hold the button to upgrade quickly.', 0.802, 0.930),
)
# 1374, a moment later: `817 7 17` and `817`.
FACILITIES_RANK1_LATER = (
    ('★', 0.120, 0.047), ('One Step at a Time', 0.208, 0.047), ('11.91K', 0.958, 0.046), ('Rules of Gooal', 0.165, 0.132),
    ('N', 0.212, 0.122), ('817 7 17', 0.778, 0.106), ('817', 0.923, 0.106), ('0/54', 0.171, 0.203), ('Order', 0.190, 0.166),
    ('へ', 0.714, 0.195), ('Manage', 0.087, 0.295), ('Facilities', 0.802, 0.272), ('Recruit', 0.084, 0.382),
    ('o Merry-Go-Round', 0.782, 0.351), ('Lv.7/50', 0.929, 0.350), ('Comfort +7', 0.784, 0.402), ('+8/6s', 0.891, 0.403),
    ('Operate', 0.085, 0.473), ('强化', 0.773, 0.456), ('34', 0.956, 0.454), ('o Tagada', 0.752, 0.530), ('LV.8/50', 0.930, 0.529),
    ('Happiness +8', 0.792, 0.580), ('+6/4s', 0.886, 0.580), ('强化', 0.773, 0.634), ('69', 0.956, 0.632), ('o Roller Coaster', 0.772, 0.706),
    ('LV.8/50', 0.930, 0.706), ('Thrill +8', 0.776, 0.758), ('+13/5s', 0.884, 0.758), ('强化', 0.772, 0.812), ('69', 0.957, 0.810),
    ('o Top Spin', 0.755, 0.885), ('Press and hold the button to upgrade quickly.', 0.802, 0.930),
)
# 1378, the Rank 2 result.
RANK2_RESULT = (
    ('Gne Step at a Time', 0.204, 0.048), ('13.32K', 0.956, 0.045), ('fohe Step at a', 0.117, 0.258), ('ment', 0.697, 0.260),
    ('the Buzz Is About', 0.855, 0.256), ('★★★★', 0.953, 0.256), ('RANK', 0.070, 0.345), ('RANK5', 0.851, 0.344),
    ('One Step at a Time', 0.501, 0.409), ('★★★★★★★★', 0.499, 0.445), ('Rank 2 Achieved', 0.500, 0.522),
    ('· Max Offline Time + 10 min', 0.502, 0.660), ('New Story Available', 0.672, 0.860), ('Achievement Complete', 0.152, 0.901),
    ('点击屏幕关闭窗口', 0.501, 0.939),
)
# 1385, the Rank screen with Rank 3 earned: Rank Up on the Rank 3 card.
RANK3_READY = (
    ('√', 0.041, 0.043), ('2', 0.096, 0.046), ('One Step at a Time', 0.206, 0.047), ('17.62K', 0.957, 0.046),
    ('Amusement Park Rank', 0.501, 0.137), ("'One Step ata Time★★★★★★★★", 0.207, 0.257),
    ('*The Amusement Park All the Buzz Is About ★★★+', 0.784, 0.256), ('RANK2', 0.074, 0.346), ('RANK 3', 0.327, 0.349),
    ('RANK 4', 0.599, 0.346), ('RANK5', 0.849, 0.347), ('oObjective', 0.078, 0.408), ('oObjective', 0.330, 0.407),
    ('。Objective', 0.602, 0.408), ('oObjective', 0.853, 0.408), ('·Thrill', 0.080, 0.462), ('717', 0.239, 0.464), ('·Thrill', 0.331, 0.463),
    ('14 / 14', 0.483, 0.461), ('·Thril', 0.603, 0.463), ('14/21', 0.754, 0.463), ('·Thril', 0.855, 0.462), ('·🎯Comfort', 0.091, 0.512),
    ('717', 0.238, 0.513), ('·🎯Comfort', 0.342, 0.511), ('14 / 14', 0.483, 0.513), ('· Comfort', 0.614, 0.513), ('14/21', 0.753, 0.513),
    ('·Comfort', 0.866, 0.513), ('• Happiness', 0.101, 0.564), ('717', 0.239, 0.563), ('•', 0.315, 0.565), ('Happiness', 0.362, 0.562),
    ('14/ 14', 0.482, 0.563), ('· Happiness', 0.621, 0.564), ('14/21', 0.754, 0.563), ('· Happiness', 0.876, 0.564),
    ('o Rank Up Benefits', 0.105, 0.624), ('o Rank Up Benefits', 0.357, 0.624), ('o Rank Up Benefits', 0.629, 0.624),
    ('o Rank Up Benefits', 0.880, 0.624), ('• Max Offline Time + 10 min', 0.128, 0.679), ('· Max manager count +1', 0.371, 0.706),
    ('• Max Offline Time + 10 min', 0.379, 0.679), ('·[Luke], [Beryl],[Lucas] can be', 0.666, 0.706),
    ('• Max Offline Time + 10 min', 0.652, 0.679), ('· Max Offline Time + 10 min', 0.903, 0.678), ('·[Top Spin]unlocked', 0.364, 0.738),
    ('assigned as managers', 0.637, 0.739), ('·[Drop Tower] unlocked', 0.897, 0.708), ('Achievement Complete', 0.152, 0.900),
    ('Rank Up', 0.402, 0.900), ('New Story Available', 0.673, 0.860), ('……', 0.674, 0.899),
)
# 1388, Rank 4 earned: Rank Up on the Rank 4 card.
RANK4_READY = (
    ('√', 0.042, 0.044), ('3', 0.097, 0.047), ('One Step at a Time', 0.202, 0.047), ('13.42K', 0.958, 0.046),
    ('Amusement Park Rank', 0.499, 0.135), ('ne★★★★★★★★', 0.104, 0.256), ('The Amusement Park All the Buzz Is About★★★★★★★★', 0.654, 0.256),
    ('RANK3', 0.159, 0.348), ('RANK 4', 0.431, 0.347), ('RANK5', 0.682, 0.347), ('RANK6', 0.934, 0.344), ('oObjective', 0.162, 0.408),
    ('oObjective', 0.434, 0.408), ('oObjective', 0.685, 0.408), ('。Objective', 0.938, 0.408), ('717', 0.071, 0.464),
    ('·Thrill', 0.164, 0.464), ('14/14', 0.315, 0.463), ('•Thrilll', 0.436, 0.463), ('21/21', 0.585, 0.464), ('·Thrill', 0.688, 0.464),
    ('21/29', 0.835, 0.464), ('·Thrill', 0.940, 0.464), ('717', 0.070, 0.514), ('·Comfort', 0.174, 0.513), ('14/14', 0.314, 0.513),
    ('Comfort', 0.449, 0.512), ('21/21', 0.585, 0.514), ('·Comfort', 0.698, 0.513), ('21/29', 0.835, 0.512), ('·Comfort', 0.949, 0.513),
    ('717', 0.071, 0.564), ('· Happiness', 0.182, 0.564), ('14/ 14', 0.314, 0.564), ('• Happiness', 0.454, 0.564), ('21/21', 0.585, 0.563),
    ('• Happiness', 0.706, 0.564), ('21/29', 0.836, 0.562), ('• Happine', 0.952, 0.564), ('o Rank Up Benefits', 0.189, 0.624),
    ('o Rank Up Benefits', 0.461, 0.625), ('o Rank Up Benefits', 0.712, 0.624), ('o Rank Up Be', 0.944, 0.624), ('nin', 0.030, 0.680),
    ('• Max Offline Time + 10 min', 0.211, 0.679), ('• Max manager count +1', 0.205, 0.708), ('assigned as managers', 0.469, 0.739),
    ('· [Luke], [Beryl], [Lucas] can be', 0.498, 0.707), ('• Max Offline Time + 10 min', 0.484, 0.679),
    ('• Max Offline Time + 10 min', 0.735, 0.679), ('·[Drop Tower] unlocked', 0.729, 0.706), ('· Max Offline T', 0.949, 0.679),
    ('·[Top Spin]unlocked', 0.197, 0.738), ('New Story Available', 0.506, 0.860), ('nplete', 0.043, 0.902),
    ('Achievement Complete', 0.235, 0.900), ('Rank Up', 0.507, 0.902),
)
# 1391, the Rank 4 result.
RANK4_RESULT = (
    ('usement Park All the Buzz Is Abot', 0.351, 0.046), ('15.26K', 0.956, 0.045), ('The Amuse', 0.209, 0.257), ('ment Park', 0.292, 0.259),
    ('RANK 4', 0.176, 0.345), ('The Amusement Park All the Buzz Is About', 0.502, 0.411), ('★★★★★★', 0.510, 0.445),
    ('Rank 4 Achieved', 0.499, 0.520), ('· [Luke], [Beryl], [Lucas] can be assigned as managers', 0.503, 0.678),
    ('· Max Offline Time + 10 min', 0.502, 0.642), ('nplete', 0.040, 0.900), ('Achievement Complete', 0.252, 0.901),
    ('点击屏幕关闭窗口', 0.499, 0.938),
)
# 1405, Chronicles with the Rank 4 reward ready on its first row.
CHRONICLES_READY = (
    ('Event Special Rewards', 0.184, 0.045), ('N', 0.973, 0.030), ('-', 0.031, 0.126), ('5', 0.020, 0.163),
    ('nusement Park Chri', 0.099, 0.143), ('Achieve [The Amusement Park AIll the Buzz Is About]', 0.371, 0.130), ('1/7', 0.045, 0.179),
    ('1/1', 0.219, 0.202), ('30', 0.601, 0.199), ('nusement Park Mar', 0.098, 0.255), ('0/16', 0.050, 0.292),
    ("Achieve [The SS Nightmare's Most Popular Spot]", 0.359, 0.284), ('Event Special Rewards', 0.882, 0.265), ('0/1', 0.219, 0.355),
    ('1|10*+', 0.718, 0.319), ('30', 0.601, 0.353), ('Achieve [The Rising Star of the Amusement Park', 0.358, 0.437), ('0/1', 0.220, 0.507),
    ('World]', 0.226, 0.468), ('00110+', 0.718, 0.470), ('0/1', 0.219, 0.660), ('World]', 0.225, 0.621),
    ('Achieve [The Superstar of the Amusement Park', 0.355, 0.589), ('0110', 0.718, 0.624), ('Progress', 0.828, 0.680),
    ('117', 0.952, 0.678), ('Line]', 0.219, 0.774), ('Achieve [An Amusement Park With a Never-Ending', 0.366, 0.743),
    ('31d remaining', 0.910, 0.736), ('0/1', 0.219, 0.813), ('00110+', 0.718, 0.776), ('30', 0.601, 0.811),
    ('Achieve [An Amusement Park That Brings', 0.336, 0.895), ('Not achieved', 0.882, 0.864), ('Hanninessl', 0.239, 0.925),
    ('o1l1o.', 0.719, 0.928),
)
# 1436, Facilities scrolled a little: Top Spin unlocked and not built, Build at 55.44K, profit 60.42K.
FACILITIES_TOP_SPIN_BUILD = (
    ('4', 0.096, 0.044), ('The Amusement Park All the Buzz Is About', 0.316, 0.046), ('60.42K', 0.956, 0.044),
    ('Rules of Gooal', 0.165, 0.132), ('N', 0.212, 0.122), ('25/29', 0.700, 0.105), ('26129', 0.795, 0.105), ('26/29', 0.929, 0.106),
    ('0/54', 0.171, 0.204), ('Order', 0.189, 0.167), ('へ', 0.714, 0.195), ('i', 0.033, 0.295), ('Manage.', 0.088, 0.295),
    ('Facilities', 0.803, 0.275), ('Recruit', 0.084, 0.382), ('o Tagada', 0.751, 0.387), ('Lv.26/50', 0.934, 0.385),
    ('Operate', 0.086, 0.472), ('Happiness +26', 0.795, 0.438), ('+21/4s', 0.893, 0.438), ('六', 0.033, 0.479), ('强化', 0.772, 0.493),
    ('3.69K', 0.946, 0.490), ('o Roller Coaster', 0.771, 0.565), ('Lv.25/50', 0.933, 0.565), ('Thrill +25', 0.780, 0.615),
    ('+40/5s', 0.895, 0.617), ('强化', 0.772, 0.670), ('3.07K', 0.946, 0.669), ('o Top Spin', 0.755, 0.744), ('Thrill +0', 0.777, 0.794),
    ('+0/5s', 0.891, 0.794), ('Build', 0.761, 0.845), ('55.44K', 0.942, 0.845),
    ('Press and hold the button to upgrade quickly.', 0.802, 0.930),
)
# 1437, after the build: Top Spin Lv.1.
FACILITIES_TOP_SPIN_BUILT = (
    ('4', 0.098, 0.045), ('🌟', 0.117, 0.048), ('The Amusement Park All the Buzz Is About', 0.314, 0.046), ('5.88K', 0.960, 0.047),
    ('Rules of Gooal', 0.165, 0.132), ('N', 0.212, 0.122), ('27/29  26 /29', 0.751, 0.105), ('😊', 0.874, 0.106), ('26/29', 0.929, 0.106),
    ('0/54', 0.171, 0.204), ('Order', 0.190, 0.169), ('へ', 0.714, 0.195), ('Manage', 0.087, 0.294), ('Facilities', 0.803, 0.275),
    ('Recruit', 0.084, 0.382), ('o Tagada', 0.751, 0.387), ('Lv.26/50', 0.934, 0.385), ('Operate', 0.088, 0.473),
    ('Happiness +26', 0.795, 0.438), ('+21/4s', 0.893, 0.438), ('强化', 0.772, 0.493), ('3.69K', 0.945, 0.490),
    ('o Roller Coaster', 0.771, 0.565), ('Lv.25/50', 0.933, 0.564), ('Thrill +25', 0.779, 0.615), ('+40/5s', 0.895, 0.617),
    ('强化', 0.772, 0.670), ('3.07K', 0.947, 0.669), ('★', 0.422, 0.754), ('o Top Spin', 0.756, 0.743), ('Lv.1/50', 0.928, 0.744),
    ('Thrill +2', 0.776, 0.794), ('+2/5s', 0.891, 0.794), ('强化', 0.772, 0.848), ('22', 0.956, 0.845),
    ('Press and hold the button to upgrade quickly.', 0.802, 0.930),
)
# 1442, the list scrolled to the locked rides.
FACILITIES_LOCKED = (
    ('5', 0.098, 0.047), ('← The Amusement Park All the Buzz Is About', 0.308, 0.046), ('7.01K', 0.961, 0.046),
    ('Rules of Goodl', 0.165, 0.131), ('N', 0.211, 0.122), ('61/36 29 /36 29/36', 0.807, 0.105), ('0/54', 0.171, 0.204),
    ('Order', 0.190, 0.168), ('Manage', 0.087, 0.293), ('Facilities', 0.803, 0.273), ('Recruit', 0.084, 0.382),
    ('Reach Amusement Park Rank 8', 0.849, 0.357), ('o Photo Booth', 0.767, 0.430), ('Operate', 0.086, 0.472), ('Comfort +0', 0.783, 0.482),
    ('+0/6s', 0.893, 0.482), ('Reach Amusement Park Rank 10', 0.851, 0.533), ('o Haunted House', 0.777, 0.608), ('Thrill +0', 0.767, 0.660),
    ('+0/5s', 0.891, 0.660), ('Reach Amusement Park Rank 12', 0.852, 0.713), ('o Observatory', 0.766, 0.787),
    ('Happiness +0', 0.791, 0.838), ('+0/6s', 0.892, 0.838), ('A Reach Amusement Park Rank 15', 0.843, 0.890),
    ('Press and hold the button to upgrade quickly.', 0.803, 0.931),
)
# 1444, scrolled to Drop Tower: a button cut off at the top with no name, Drop Tower's Build at 385.00K.
FACILITIES_DROP_TOWER = (
    ('5', 0.097, 0.047), ('The Amusement Park All the Buzz Is About', 0.314, 0.046), ('8.56K', 0.960, 0.047),
    ("Rules of Good'", 0.165, 0.133), ('N', 0.211, 0.122), ('61/3629 /36', 0.767, 0.106), ('29/36', 0.929, 0.106), ('0/54', 0.171, 0.204),
    ('Order', 0.190, 0.168), ('へ', 0.714, 0.195), ('」', 0.033, 0.296), ('Manage', 0.087, 0.294), ('Facilities', 0.803, 0.274),
    ('强化', 0.772, 0.345), ('6.37K', 0.947, 0.344), ('Recruit', 0.085, 0.382), ('o Roller Coaster', 0.771, 0.419),
    ('Lv.25/50', 0.934, 0.419), ('六', 0.033, 0.479), ('Operate', 0.088, 0.473), ('Thrill +25', 0.780, 0.469), ('+40/5s', 0.894, 0.469),
    ('强化', 0.773, 0.524), ('3.07K', 0.946, 0.522), ('o Top Spin', 0.755, 0.596), ('Lv.18/50', 0.933, 0.596), ('Thrill +36', 0.779, 0.647),
    ('+36/5s', 0.895, 0.648), ('强化', 0.772, 0.701), ('2.19K', 0.946, 0.700), ('o Drop Tower', 0.765, 0.774), ('Comfort +0', 0.783, 0.825),
    ('+0/4s', 0.890, 0.825), ('Build', 0.761, 0.879), ('385.00K', 0.924, 0.878),
    ('Press and hold the button to upgrade quickly.', 0.802, 0.930),
)
# 1448, the Manage panel at Rank 5: Profit Status 89/s, Max Idle Time 7h 30m.
MANAGE_RANK5 = (
    ('5', 0.097, 0.046), ('The Amusement Park All the Buzz Is About', 0.315, 0.046), ('871', 0.966, 0.047), ('Rules of Good', 0.165, 0.133),
    ('N', 0.212, 0.122), ('0/54', 0.171, 0.203), ('Order', 0.190, 0.169), ('Manage', 0.803, 0.139), ('Manage', 0.085, 0.294),
    ('The Amusement Park All the Buzz Is About Rank 5', 0.804, 0.313), ('Recruit', 0.084, 0.383), ('o Profit Status', 0.691, 0.398),
    ('89/s', 0.936, 0.397), ('Operate', 0.087, 0.473), ('o Total Profit', 0.686, 0.454), ('139.01K', 0.928, 0.452),
    ('o Max Simultaneous Visitors', 0.741, 0.509), ('3', 0.952, 0.508), ('o Max Idle Time', 0.696, 0.564), ('7h 30m', 0.929, 0.563),
    ('o Visitor Emotions', 0.705, 0.633), ('Thril', 0.706, 0.675), ('61/36', 0.936, 0.675), ('Comfort', 0.716, 0.744),
    ('34 /36', 0.935, 0.744), ('>>>>>>>>', 0.401, 0.823), ('>>>>>>>>', 0.475, 0.823), ('Happiness', 0.721, 0.811), ('29/36', 0.934, 0.807),
    ('Amusement Park Rank', 0.804, 0.906),
)
# 1390, a park story playing, its dialogue bar showing.
STORY = (
    ('R', 0.831, 0.077), ('Ctrl', 0.894, 0.078), ('Q', 0.959, 0.078), ('★', 0.184, 0.557), ('-', 0.320, 0.557), ('Lucas', 0.121, 0.755),
    ('Captain! Over here, over here! Iheard the news about the opening and came running!', 0.470, 0.835), ('Space', 0.937, 0.912),
)


def edited(screen, *changes):
    """Give a screen with some of its texts read differently, as the same screen shows them a press later.

    Args:
        screen: `(name, x, y)` triples.
        changes: `(old, new)` pairs, or `(old, new, x)` where the same text reads at several places; a new text of None
            drops the box.

    Returns:
        The edited triples.
    """
    out = []
    for name, x, y in screen:
        change = next((change for change in changes if change[0] == name and (len(change) == 2 or abs(change[2] - x) < 0.005)), None)
        if change is not None:
            name = change[1]
        if name is not None:
            out.append((name, x, y))
    return tuple(out)


RANK_UP_CROP = (0.06, 0.025)


def rank_frame(name, centre):
    """Put a Rank Up crop back where it was cut, centred on its caption."""
    x, y = centre
    return placed(name, (x - RANK_UP_CROP[0], y - RANK_UP_CROP[1], x + RANK_UP_CROP[0], y + RANK_UP_CROP[1]))


# Where each Rank Up crop was cut, centred on the caption OCR read.
LIVE_RANK3 = rank_frame("dream_park_rank_up_live", (0.402, 0.900))
LIVE_RANK6 = rank_frame("dream_park_rank_up_live_rank6", (0.502, 0.900))
GREY_RANK1 = rank_frame("dream_park_rank_up_grey", (0.152, 0.902))
GREY_AFTER = rank_frame("dream_park_rank_up_grey_after", (0.503, 0.902))


def claim_frame(*rows):
    """Lay the claim crops into an otherwise black frame: the orange ring or the grey waveform, one per row's claim point.

    Args:
        rows: `(ready, y)` pairs, y the claim point's centre.

    Returns:
        A `(height, width, 3)` BGR array.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for ready, y in rows:
        patch = cv2.imread(str(REPO_ROOT / "tests" / "images" / f"dream_park_claim_{'arrow' if ready else 'none'}.png"))
        left, top = int(0.700 * WIDTH), int((y - 0.030) * HEIGHT)
        frame[top:top + patch.shape[0], left:left + patch.shape[1]] = patch
    return frame


# The claim points of the six rows the achievements list shows from its top.
ROWS = (0.166, 0.319, 0.471, 0.624, 0.776, 0.928)
NONE_READY = claim_frame(*((False, y) for y in ROWS))
FIRST_READY = claim_frame((True, ROWS[0]), *((False, y) for y in ROWS[1:]))

# Where the park presses, beyond Daily's own targets, and what it must never press.
PARK_NEVER = {
    "the Rules of Good Order banner": (0.803, 0.803),
    "the Rules of Good Order's 确认": (0.667, 0.631),
    "the park's Recruit": (0.085, 0.382),
    "the park's Rules of Good Order": (0.165, 0.132),
    "an achievement's Crystal reward": (0.601, 0.199),
    "Roller Coaster's Upgrade": (0.773, 0.812),
}


class Park(Daily):
    """Daily on the park step, the mail already claimed."""

    def setUp(self):
        super().setUp()
        self.state()["steps"]["mail"], self.state()["mail"] = daily.DONE, "claimed"

    def park(self):
        return self.state()["park"]

    def show(self, texts, frame=None):
        return run_pass(self.task.show(texts, frame))

    def run_screens(self, screens):
        for screen in screens:
            texts, frame = screen if isinstance(screen, tuple) and len(screen) == 2 and isinstance(screen[1], (np.ndarray, type(None))) else (screen, None)
            self.show(texts, frame)
            self.tick()

    def fresh(self):
        """Start again on a new task, the mail claimed."""
        self.task = Task()
        self.state()["steps"]["mail"], self.state()["mail"] = daily.DONE, "claimed"

    def settled(self, screen, frame=None):
        """Show a park screen, then again once it has had time to draw."""
        self.show(screen, frame)
        self.tick(daily.SETTLE)
        return self.show(screen, frame)

    def pressed_at(self, point):
        """Say whether any tap landed on a point."""
        return any(abs(x - point[0]) < NEAR and abs(y - point[1]) < NEAR for x, y in self.task.clicks)

    def assertParkNothingForbidden(self):
        self.assertNothingForbidden()
        for name, point in PARK_NEVER.items():
            self.assertFalse(self.pressed_at(point), name)


class TestNumbers(unittest.TestCase):

    def test_park_numbers_read_with_their_suffix(self):
        """1"""
        for text, value in (("6.81K", 6_810), ("871", 871), ("11.91K", 11_910), ("139.01K", 139_010), ("385.00K", 385_000), ("1.23M", 1_230_000),
                            ("1,234.5K", 1_234_500), (" 22 ", 22)):
            with self.subTest(text=text):
                self.assertAlmostEqual(value, dream_park.parse_number(text))

    def test_anything_but_a_plain_park_number_does_not_read(self):
        """1"""
        for text in ("$4.99", "30 Crystals", "", "强化", "4.6SK", "₩1,200", "6.37K Crystal", "+201", "Lv.29/50"):
            with self.subTest(text=text):
                self.assertIsNone(dream_park.parse_number(text))

    def test_the_profit_counter_reads_and_the_floating_ticks_do_not_count(self):
        self.assertEqual(84_380, dream_park.profit(Task().show(PARK_VIEW + (("+180", 0.947, 0.143),))))
        self.assertIsNone(dream_park.profit(Task().show(edited(PARK_VIEW, ("84.38K", None)) + (("+180", 0.947, 0.143),))))

    def test_the_words_daily_presses_in_the_park_pass_its_backstop(self):
        """`+`, Build and the Upgrade caption are none of the refused words, and `+` stays out of them."""
        for text in ("Build", "强化", "+201", "+41/6s", "1|10*+", "Enter Amusement Park", "Achievements", "Rank Up", "点击屏幕关闭窗口", "取消"):
            with self.subTest(text=text):
                self.assertIsNone(daily.refused(text))
        for text in ("30 Crystals", "Crystal", "US$4.99", "Buy", "Purchase"):
            with self.subTest(text=text):
                self.assertIsNotNone(daily.refused(text))


class TestEmotions(unittest.TestCase):

    def test_the_operate_header_splits_however_ocr_runs_it_together(self):
        """2"""
        cases = {
            "three clean boxes": (FACILITIES, ((61, 34, 29), 36)),
            "run together": (FACILITIES_FLUNG, ((61, 34, 29), 36)),
            "a slash read as 1": (FACILITIES_TOP_SPIN_BUILD, ((25, 26, 26), 29)),
            "two run together and spaced": (FACILITIES_TOP_SPIN_BUILT, ((27, 26, 26), 29)),
            "one box with spaces": (FACILITIES_LOCKED, ((61, 29, 29), 36)),
            "two run together, one apart": (FACILITIES_DROP_TOWER, ((61, 29, 29), 36)),
            "a spaced slash": (FACILITIES_DONE, ((61, 36, 36), 36)),
            "the next Rank": (FACILITIES_RANK7, ((61, 38, 36), 43)),
        }
        for name, (screen, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(expected, dream_park.header_emotions(Task().show(screen)))

    def test_a_garbled_header_does_not_read(self):
        """2: Rank 1's single digits come back without a slash."""
        for screen in (FACILITIES_RANK1, FACILITIES_RANK1_LATER):
            self.assertIsNone(dream_park.header_emotions(Task().show(screen)))

    def test_a_profit_tick_floating_through_the_header_is_left_out(self):
        self.assertEqual(((61, 34, 29), 36), dream_park.header_emotions(Task().show(FACILITIES + (("+201", 0.947, 0.112),))))

    def test_a_header_that_splits_two_ways_does_not_read(self):
        """Text that splits in more than one way, or leaves digits over, is no reading: the parser takes no guess."""
        self.assertIsNone(dream_park.split_header("1/111111/1"))
        self.assertIsNone(dream_park.split_header("61/3634/36"))
        self.assertIsNone(dream_park.split_header("61/3634/3629/36201"))

    def test_the_manage_panel_reads_each_emotion_from_its_own_box(self):
        """2"""
        self.assertEqual(((61, 34, 29), 36), dream_park.manage_emotions(Task().show(MANAGE_RANK5)))
        self.assertEqual(((61, 36, 36), 36), dream_park.manage_emotions(Task().show(MANAGE)))
        self.assertEqual(((61, 36, 36), 43), dream_park.manage_emotions(Task().show(MANAGE_RANK6)))

    def test_a_garbled_or_missing_manage_value_does_not_read(self):
        garbled = tuple(("817", x, y) if name == "61/36" else (name, x, y) for name, x, y in MANAGE_RANK5)
        self.assertIsNone(dream_park.manage_emotions(Task().show(garbled)))
        self.assertIsNone(dream_park.manage_emotions(Task().show(tuple(box for box in MANAGE_RANK5 if box[0] != "29/36"))))

    def test_one_offline_stretch_is_the_profit_rate_times_the_idle_time(self):
        self.assertEqual(89 * (7 * 3600 + 30 * 60), dream_park.offline_stretch(Task().show(MANAGE_RANK5)))
        self.assertEqual(91 * (7 * 3600 + 40 * 60), dream_park.offline_stretch(Task().show(MANAGE_RANK6)))
        self.assertIsNone(dream_park.offline_stretch(Task().show(tuple(box for box in MANAGE_RANK5 if box[0] != "89/s"))))


class TestRows(unittest.TestCase):

    def rows(self, screen):
        return [(ride.name, ride.level, ride.emotion, ride.action, ride.price) for ride in dream_park.facility_rows(Task().show(screen))]

    def test_the_top_of_the_list_shows_three_rides_with_buttons(self):
        """3: Top Spin's button is cut off at the bottom, so it is no row."""
        self.assertEqual([("Merry-Go-Round", 34, "Comfort", "upgrade", 4_650), ("Tagada", 29, "Happiness", "upgrade", 6_370),
                          ("Roller Coaster", 25, "Thrill", "upgrade", 3_070)], self.rows(FACILITIES))

    def test_rank_one_rows_read_with_the_bullet_as_zero_and_lv_in_capitals(self):
        """3"""
        self.assertEqual([("Merry-Go-Round", 7, "Comfort", "upgrade", 34), ("Tagada", 2, "Happiness", "upgrade", 24),
                          ("Roller Coaster", 8, "Thrill", "upgrade", 69)], self.rows(FACILITIES_RANK1))
        self.assertEqual([("Merry-Go-Round", 7, "Comfort", "upgrade", 34), ("Tagada", 8, "Happiness", "upgrade", 69),
                          ("Roller Coaster", 8, "Thrill", "upgrade", 69)], self.rows(FACILITIES_RANK1_LATER))

    def test_an_unbuilt_ride_reads_as_a_build_at_level_zero(self):
        """3"""
        self.assertEqual(("Top Spin", 0, "Thrill", "build", 55_440), self.rows(FACILITIES_TOP_SPIN_BUILD)[-1])
        self.assertEqual(("Top Spin", 1, "Thrill", "upgrade", 22), self.rows(FACILITIES_TOP_SPIN_BUILT)[-1])

    def test_locked_rides_and_a_button_without_its_name_are_no_rows(self):
        """3"""
        self.assertEqual([], self.rows(FACILITIES_LOCKED))
        self.assertEqual([], self.rows(FACILITIES_FLUNG))
        self.assertEqual([("Roller Coaster", 25, "Thrill", "upgrade", 3_070), ("Top Spin", 18, "Thrill", "upgrade", 2_190),
                          ("Drop Tower", 0, "Comfort", "build", 385_000)], self.rows(FACILITIES_DROP_TOWER))

    def test_a_price_that_does_not_read_or_is_missing_is_none(self):
        self.assertEqual(None, self.rows(edited(FACILITIES, ("6.37K", "6.3?K")))[1][4])
        self.assertEqual(None, self.rows(edited(FACILITIES, ("6.37K", None)))[1][4])


class TestChoice(unittest.TestCase):

    def choose(self, screen, emotions=None, stretch=None):
        task = Task().show(screen)
        emotions = emotions or dream_park.header_emotions(task)
        ride, reason = dream_park.choose(dream_park.facility_rows(task), emotions, dream_park.profit(task), stretch)
        return (ride.name, ride.action) if ride is not None else reason

    def test_a_newly_unlocked_ride_is_built_before_any_upgrade(self):
        """4: Top Spin's Build at 55.44K against a profit of 60.42K."""
        self.assertEqual(("Top Spin", "build"), self.choose(FACILITIES_TOP_SPIN_BUILD))

    def test_a_build_within_one_offline_stretch_is_saved_for(self):
        """4: Drop Tower at 385.00K, the profit 8.56K, one stretch about 2.4M: nothing is pressed."""
        stretch = 89 * (7 * 3600 + 30 * 60)
        self.assertEqual("saving for Drop Tower (385,000)", self.choose(FACILITIES_DROP_TOWER, stretch=stretch))
        self.assertTrue(self.choose(FACILITIES_TOP_SPIN_BUILD, stretch=stretch)[0] == "Top Spin")

    def test_a_build_beyond_one_stretch_is_left_and_the_upgrades_go_on(self):
        self.assertEqual("no Comfort or Happiness ride with a readable price in view", self.choose(FACILITIES_DROP_TOWER, stretch=100_000))
        self.assertEqual("no Comfort or Happiness ride with a readable price in view", self.choose(FACILITIES_DROP_TOWER))

    def test_the_emotion_furthest_below_the_target_wins_never_the_cheapest_ride_of_another(self):
        """4: Happiness 29 of 36 lags most, so Tagada at 6.37K, never Roller Coaster at 3.07K for Thrill at 61."""
        self.assertEqual(("Tagada", "upgrade"), self.choose(FACILITIES))

    def test_a_tie_takes_the_cheaper_ride(self):
        """After the rank up, Comfort and Happiness both 36 of 43: Merry-Go-Round at 6.69K before Tagada at 22.81K."""
        self.assertEqual(("Merry-Go-Round", "upgrade"), self.choose(FACILITIES_DONE, emotions=((61, 36, 36), 43)))

    def test_the_lagging_ride_costing_more_than_the_profit_ends_the_upgrades(self):
        """Happiness 36 of 43 lags most; Tagada at 22.81K against 5.67K. Merry-Go-Round, cheaper, is not lagging most."""
        self.assertEqual("the next upgrade, Tagada, costs more than the profit", self.choose(FACILITIES_RANK7))

    def test_with_every_emotion_at_its_target_the_cheapest_ride_of_all(self):
        self.assertEqual(("Roller Coaster", "upgrade"), self.choose(FACILITIES_DONE))

    def test_a_row_whose_price_does_not_read_is_never_chosen(self):
        """8"""
        self.assertEqual("no Happiness ride with a readable price in view", self.choose(edited(FACILITIES, ("6.37K", "6.3?K"))))
        build = dream_park.Ride("Top Spin", 0, "Thrill", "build", None, 10, None)
        self.assertEqual((build, None), dream_park.choose([build], None, 20))
        self.assertEqual("no ride with a readable price in view", dream_park.choose(
            [dream_park.Ride("Tagada", 3, "Happiness", "upgrade", None, None, None)], ((7, 7, 7), 7), 1_000)[1])

    def test_unread_profit_or_emotions_choose_nothing(self):
        self.assertEqual("the profit did not read", self.choose(edited(FACILITIES, ("99.21K", None))))
        task = Task().show(FACILITIES_RANK1)
        self.assertEqual((None, "the emotions did not read"), dream_park.choose(dream_park.facility_rows(task), None, 9_820))

    def test_a_ride_at_its_level_cap_is_never_chosen(self):
        capped = [dream_park.Ride("Merry-Go-Round", 50, "Comfort", "upgrade", None, 10, None)]
        self.assertEqual((None, "no ride with a readable price in view"), dream_park.choose(capped, ((61, 61, 61), 57), 1_000))


class TestRankUp(Park):

    def test_rank_up_is_found_on_whichever_card_it_is_drawn(self):
        """5"""
        for screen, x in ((RANK_UNEARNED, 0.152), (RANK3_READY, 0.402), (RANK4_READY, 0.507), (RANK_READY, 0.502), (RANK_AFTER, 0.503)):
            with self.subTest(x=x):
                box = dream_park.rank_up_button(Task().show(screen))
                self.assertAlmostEqual(x, daily.centre_of(box, WIDTH, HEIGHT)[0], delta=0.002)

    def test_only_the_blue_pill_is_live(self):
        """5"""
        for screen, frame, live in ((RANK3_READY, LIVE_RANK3, True), (RANK_READY, LIVE_RANK6, True), (RANK_UNEARNED, GREY_RANK1, False),
                                    (RANK_AFTER, GREY_AFTER, False), (RANK_READY, None, False)):
            with self.subTest(live=live, frame=frame is not None):
                box = dream_park.rank_up_button(Task().show(screen))
                self.assertEqual(live, dream_park.rank_up_live(frame, box, WIDTH, HEIGHT))

    def test_a_live_rank_up_is_pressed_and_a_grey_one_closes_the_screen(self):
        """5"""
        self.show(RANK_READY, LIVE_RANK6)
        self.assertPressed(daily.RANK_UP)
        self.fresh()
        self.show(RANK_UNEARNED, GREY_RANK1)
        self.assertPressed(daily.RANK_CLOSE)

    def test_the_grey_rank_up_left_after_a_rank_up_is_never_pressed(self):
        """The caption stays on the next card after a rank up."""
        self.park()["emotions"] = ((61, 36, 36), 36)
        self.show(RANK_AFTER, GREY_AFTER)
        self.assertPressed(daily.RANK_CLOSE)
        self.assertEqual(36, self.park()["rank_checked"])

    def test_negative_control_without_the_colour_test_the_grey_rank_up_is_pressed(self):
        """Proves the test above bites: with the colour test gone, the grey caption after a rank up would be pressed again."""
        with mock.patch.object(dream_park, "rank_up_live", lambda frame, box, width, height: True):
            self.show(RANK_AFTER, GREY_AFTER)
        with self.assertRaises(AssertionError):
            self.assertPressed(daily.RANK_CLOSE)

    def test_rank_up_waits_for_its_result_then_retries_once_then_stops(self):
        self.task.show(RANK_READY, LIVE_RANK6)
        for _ in range(2 * daily.RANK_WAIT):
            run_pass(self.task)
            self.tick()
        self.assertPressed(daily.RANK_UP, daily.RANK_UP)
        self.assertTrue(run_pass(self.task))
        self.assertStopped("Rank Up was pressed 2 times")

    def test_the_result_is_closed_on_its_caption_and_counted(self):
        """6"""
        self.show(RANK_READY, LIVE_RANK6)
        self.tick()
        self.show(RANK_RESULT)
        self.assertPressed(daily.RANK_UP, daily.RANK_RESULT_CLOSE)
        self.assertEqual(1, self.park()["rank_ups"])
        for screen in (RANK2_RESULT, RANK4_RESULT):
            with self.subTest(screen=screen[-1][0]):
                self.fresh()
                self.show(screen)
                self.assertPressed(daily.RANK_RESULT_CLOSE)
                self.assertEqual(0, self.park()["rank_ups"])


class TestManageAndFacilities(Park):

    def test_the_manage_panel_opens_the_rank_only_with_every_emotion_at_its_target(self):
        self.show(MANAGE)
        self.assertPressed(daily.PARK_RANK)
        self.assertEqual([5], self.park()["ranks"])
        self.task.clicks.clear()
        self.park()["rank_checked"] = 36
        self.tick(daily.NAV_WAIT)
        self.show(MANAGE)
        self.assertPressed(daily.PARK_OPERATE)
        self.fresh()
        self.show(MANAGE_RANK5)
        self.assertPressed(daily.PARK_OPERATE)
        self.assertEqual(89 * 27_000, self.park()["stretch"])

    def test_the_rules_of_good_order_get_cancel_never_confirm(self):
        """6"""
        for cancel in ("取消", "Cancel"):
            with self.subTest(cancel=cancel):
                self.fresh()
                self.show(edited(RULES, ("取消", cancel)))
                self.assertPressed(daily.RULES_CANCEL)
                self.assertParkNothingForbidden()

    def test_one_upgrade_per_pass_on_the_lagging_ride_then_waits_for_its_level(self):
        self.park()["phase"] = daily.TO_OPERATE
        self.show(FACILITIES)
        self.assertPressed(daily.UPGRADE)
        self.tick()
        self.show(FACILITIES)
        self.assertEqual(1, len(self.task.clicks))
        self.tick()
        self.show(edited(FACILITIES, ("Lv.29/50", "Lv.30/50"), ("29/36", "30/36"), ("99.21K", "93.72K"), ("6.37K", "7.64K")))
        self.assertPressed(daily.UPGRADE, daily.UPGRADE)
        self.assertEqual(2, self.park()["upgrades"])
        self.assertParkNothingForbidden()

    def test_two_presses_without_a_level_rise_stop(self):
        """8"""
        self.park()["phase"] = daily.TO_OPERATE
        self.task.show(FACILITIES)
        for _ in range(2 * daily.UPGRADE_WAIT + 1):
            run_pass(self.task)
            self.tick()
        self.assertPressed(daily.UPGRADE, daily.UPGRADE)
        self.assertStopped("did not take two presses on Tagada")

    def test_negative_control_without_the_level_check_the_presses_go_on(self):
        """Proves the test above bites."""
        self.park()["phase"] = daily.TO_OPERATE
        self.task.show(FACILITIES)
        with mock.patch.object(daily, "ride_risen", lambda task, rows: None):
            for _ in range(2 * daily.UPGRADE_WAIT + 1):
                run_pass(self.task)
                self.tick()
        self.assertEqual(0, self.task.disabled)
        self.assertGreater(len(self.task.clicks), 2)

    def test_a_price_reading_as_crystals_stops_daily(self):
        """8"""
        self.park()["phase"] = daily.TO_OPERATE
        self.show(edited(FACILITIES, ("6.37K", "30 Crystals")))
        self.assertEqual([], self.task.clicks)
        self.assertStopped("a Dream Park price reads '30 Crystals'")

    def test_a_crystal_or_money_box_anywhere_in_a_rows_price_column_stops_daily(self):
        """Right of Tagada's price, left of it, and on its emotion line between the name and the button: OCR's order on a
        line decides nothing."""
        cases = {"Crystal right of the price": ("Crystal", 0.975, 0.632), "money right of the price": ("US$4.99", 0.975, 0.632),
                 "Crystal left of the price": ("Crystal", 0.900, 0.632), "Crystal between name and button": ("Crystal", 0.950, 0.580),
                 "Crystal on the name line": ("Crystal", 0.975, 0.530)}
        for name, box in cases.items():
            with self.subTest(name):
                self.fresh()
                self.park()["phase"] = daily.TO_OPERATE
                self.show(FACILITIES + (box,))
                self.assertEqual([], self.task.clicks)
                self.assertStopped(f"a Dream Park price reads {box[0]!r}")

    def test_a_clean_list_still_upgrades_with_every_box_in_its_price_columns_read(self):
        self.park()["phase"] = daily.TO_OPERATE
        self.show(FACILITIES)
        self.assertPressed(daily.UPGRADE)
        self.assertEqual(0, self.task.disabled)
        tagada = dream_park.facility_rows(Task().show(FACILITIES))[1]
        self.assertEqual(["Lv.29/50", "+23/4s", "6.37K"], [box.name for box in tagada.price_column])

    def test_negative_control_without_the_price_check_crystals_go_unremarked(self):
        """Proves the test above bites. The Crystal price still reads as no park number, so it is not pressed either way."""
        self.park()["phase"] = daily.TO_OPERATE
        with mock.patch.object(daily, "refused", lambda text: None):
            self.show(edited(FACILITIES, ("6.37K", "30 Crystals")))
        self.assertEqual(0, self.task.disabled)
        self.assertFalse(self.pressed_at(POINTS[daily.UPGRADE]))

    def test_an_unread_price_is_never_pressed(self):
        """8: Tagada is the lagging ride, but its price does not read; the visit leaves the list instead."""
        self.park()["phase"] = daily.TO_OPERATE
        self.settled(edited(FACILITIES, ("6.37K", "6.3?K")))
        self.assertPressed(daily.PANEL_CLOSE)
        self.assertEqual("no Happiness ride with a readable price in view", self.park()["note"])

    def test_negative_control_with_a_lenient_price_reader_the_unread_price_is_pressed(self):
        """Proves the test above bites."""
        self.park()["phase"] = daily.TO_OPERATE
        original = dream_park.parse_number
        with mock.patch.object(dream_park, "parse_number", lambda text: original(text) if original(text) is not None else 0.0):
            self.show(edited(FACILITIES, ("6.37K", "6.3?K")))
        self.assertTrue(self.pressed_at(POINTS[daily.UPGRADE]))

    def test_every_emotion_at_its_target_goes_to_the_rank_first_and_once_tried_upgrades_the_cheapest(self):
        self.park()["phase"] = daily.TO_OPERATE
        self.show(FACILITIES_DONE)
        self.assertPressed(daily.PARK_MANAGE)
        self.assertEqual(daily.TO_MANAGE, self.park()["phase"])
        self.task.clicks.clear()
        self.park()["phase"], self.park()["rank_checked"] = daily.TO_OPERATE, 36
        self.show(FACILITIES_DONE)
        self.assertEqual(1, len(self.task.clicks))
        self.assertAlmostEqual(0.812, self.task.clicks[0][1], delta=0.005)

    def test_an_unreadable_manage_panel_counts_the_header_target_as_tried_so_the_visit_does_not_shuttle(self):
        """The header reads every emotion at 36, the panel's values do not read: one trip to Manage, then the upgrades."""
        garbled = edited(MANAGE, ("61/36", "817"))
        self.park()["phase"] = daily.TO_OPERATE
        self.run_screens([FACILITIES_DONE] + [garbled] * (daily.SETTLE + 1) + [FACILITIES_DONE])
        self.assertEqual(3, len(self.task.clicks), self.task.clicks)
        self.assertTrue(self.pressed_at(POINTS[daily.PARK_MANAGE]))
        self.assertTrue(self.pressed_at(POINTS[daily.PARK_OPERATE]))
        self.assertAlmostEqual(0.812, self.task.clicks[2][1], delta=0.005)
        self.assertFalse(self.pressed_at(POINTS[daily.PARK_RANK]))
        self.assertEqual(36, self.park()["rank_checked"])
        self.assertEqual(0, self.task.disabled)

    def test_the_shuttle_between_facilities_and_an_unreadable_manage_panel_is_bounded(self):
        """Following each press to the screen it leads to for a whole visit's time: one round trip, never the overtime stop."""
        garbled = edited(MANAGE, ("61/36", "817"))
        self.park()["phase"] = daily.TO_OPERATE
        screen = FACILITIES_DONE
        for _ in range(daily.PARK_SECONDS):
            before = len(self.task.clicks)
            self.show(screen)
            self.tick()
            if len(self.task.clicks) > before:
                last = self.task.clicks[-1]
                if last == POINTS[daily.PARK_MANAGE]:
                    screen = garbled
                elif last == POINTS[daily.PARK_OPERATE]:
                    screen = FACILITIES_DONE
                else:
                    break
        navigation = [click for click in self.task.clicks if click in (POINTS[daily.PARK_MANAGE], POINTS[daily.PARK_OPERATE])]
        self.assertEqual(2, len(navigation), self.task.clicks)
        self.assertNotIn("ran for", " ".join(self.task.notifications))

    def test_a_garbled_header_falls_back_to_the_manage_read_until_the_first_upgrade(self):
        """2"""
        self.park()["phase"], self.park()["emotions"] = daily.TO_OPERATE, ((8, 7, 2), 7)
        self.show(FACILITIES_RANK1)
        self.assertEqual(1, len(self.task.clicks))
        self.assertAlmostEqual(0.634, self.task.clicks[0][1], delta=0.005)
        self.tick(daily.UPGRADE_WAIT)
        rose = tuple(("LV.3/50", x, y) if name == "LV.2/50" else (name, x, y) for name, x, y in FACILITIES_RANK1)
        self.show(rose)
        self.assertEqual("the emotions did not read", self.park()["note"])

    def test_a_list_still_drawing_is_waited_on_before_the_visit_leaves_it(self):
        self.park()["phase"] = daily.TO_OPERATE
        bare = tuple(box for box in FACILITIES if box[1] < 0.70 or box[0] in ("Facilities", "Press and hold the button to upgrade quickly."))
        self.show(bare)
        self.assertEqual([], self.task.clicks)
        self.tick(daily.SETTLE)
        self.show(bare)
        self.assertPressed(daily.PANEL_CLOSE)

    def test_the_visit_stops_upgrading_at_its_cap(self):
        self.park()["phase"], self.park()["upgrades"] = daily.TO_OPERATE, daily.UPGRADE_CAP
        self.show(FACILITIES)
        self.assertPressed(daily.PANEL_CLOSE)
        self.assertIn("200 upgrades", self.park()["note"])

    def test_a_build_is_pressed_and_its_level_rise_awaited(self):
        """Once Top Spin shows Lv.1 the visit goes on: Comfort and Happiness lag, and Tagada at 3.69K is the one in view."""
        self.park()["phase"] = daily.TO_OPERATE
        self.show(FACILITIES_TOP_SPIN_BUILD)
        self.assertPressed(daily.BUILD)
        self.tick()
        self.show(FACILITIES_TOP_SPIN_BUILT)
        self.assertEqual(["Top Spin"], self.park()["builds"])
        self.assertEqual(0, self.park()["no_rise"]["Top Spin"])
        self.assertEqual(("Tagada", 26), self.park()["pending"][:2])
        self.assertAlmostEqual(0.493, self.task.clicks[1][1], delta=0.005)

    def test_the_park_view_opens_manage_first_then_operate_then_leaves(self):
        self.show(PARK_VIEW)
        self.assertPressed(daily.PARK_MANAGE)
        self.tick(daily.NAV_WAIT)
        self.park()["phase"] = daily.TO_OPERATE
        self.show(PARK_VIEW)
        self.tick(daily.NAV_WAIT)
        self.park()["phase"] = daily.TO_LEAVE
        self.show(PARK_VIEW)
        self.assertPressed(daily.PARK_MANAGE, daily.PARK_OPERATE, daily.PARK_LEAVE)

    def test_a_park_press_is_not_repeated_while_its_screen_may_still_change(self):
        """A second Operate on the open panel would close it."""
        self.show(PARK_VIEW)
        for _ in range(daily.NAV_WAIT - 1):
            self.tick()
            self.show(PARK_VIEW)
        self.assertPressed(daily.PARK_MANAGE)

    def test_a_story_the_step_does_not_know_stops_daily_with_nothing_pressed(self):
        for _ in range(daily.UNKNOWN_SECONDS):
            self.show(STORY)
            self.tick()
        self.show(STORY)
        self.assertEqual([], self.task.clicks)
        self.assertStopped("Daily does not know this screen")


class TestAchievements(Park):

    def test_the_ready_ring_is_found_and_grey_rows_are_not(self):
        """7"""
        self.assertEqual([(0.722, ROWS[0])], [(x, round(y, 3)) for x, y in dream_park.ready_claims(Task().show(CHRONICLES_READY), FIRST_READY)])
        self.assertEqual([], dream_park.ready_claims(Task().show(CHRONICLES_READY), NONE_READY))
        self.assertEqual([], dream_park.ready_claims(Task().show(CHRONICLES), NONE_READY))
        self.assertEqual([], dream_park.ready_claims(Task().show(MANAGEMENT), NONE_READY))
        self.assertEqual([], dream_park.ready_claims(Task().show(CHRONICLES_READY), None))

    def test_a_claimed_row_carries_no_text_and_is_never_pressed(self):
        """A claimed row shows only `1/1` and a check, so readiness is the orange ring, never a missing `Claimed`."""
        task = Task().show(CHRONICLES_SCROLLED)
        frame = claim_frame(*((False, y) for y in (0.094, 0.247, 0.400, 0.552, 0.704)))
        patch = cv2.imread(str(REPO_ROOT / "tests" / "images" / "dream_park_claim_done.png"))
        frame[int(0.828 * HEIGHT):int(0.828 * HEIGHT) + patch.shape[0], int(0.700 * WIDTH):int(0.700 * WIDTH) + patch.shape[1]] = patch
        self.assertEqual([], dream_park.ready_claims(task, frame))
        self.settled(CHRONICLES_SCROLLED, frame)
        self.assertPressed(daily.MANAGEMENT_TAB)

    def test_a_ready_ring_is_pressed_items_obtained_closed_and_the_claim_counted(self):
        """7"""
        self.settled(CHRONICLES_READY, FIRST_READY)
        self.assertPressed(daily.CLAIM)
        self.tick()
        self.show(ITEMS)
        self.assertPressed(daily.CLAIM, daily.ITEMS_CLOSE)
        self.assertEqual(1, self.park()["claims"])
        self.assertParkNothingForbidden()

    def test_both_tabs_are_checked_then_the_page_is_left_with_no_grey_row_pressed(self):
        """7"""
        self.run_screens([(CHRONICLES, NONE_READY)] * (daily.SETTLE + 1) + [(MANAGEMENT, NONE_READY)] * (daily.NAV_WAIT + 1))
        self.assertPressed(daily.MANAGEMENT_TAB, daily.ACHIEVEMENTS_LEAVE)
        self.assertTrue(self.park()["claims_done"])

    def test_two_claims_that_open_nothing_stop(self):
        self.task.show(CHRONICLES_READY, FIRST_READY)
        for _ in range(daily.SETTLE + 2 * daily.CLAIM_WAIT + 1):
            run_pass(self.task)
            self.tick()
        self.assertPressed(daily.CLAIM, daily.CLAIM)
        self.assertStopped("two Dream Park achievement claims opened nothing")


class TestEventGone(Park):

    def test_an_event_list_without_dream_park_ends_the_step_without_a_stop(self):
        """8"""
        self.run_screens([EVENT_LIST_WITHOUT_PARK] * (daily.SETTLE + 1) + [LOBBY])
        self.assertPressed(daily.EVENT_LEAVE)
        self.assertStopped("Daily finished: mail claimed; Dream Park is not running")

    def test_an_event_page_without_enter_ends_the_step_without_a_stop(self):
        self.run_screens([tuple(box for box in PAGE if box[0] != "Enter Amusement Park")] * (daily.SETTLE + 1) + [LOBBY])
        self.assertPressed(daily.PAGE_LEAVE)
        self.assertStopped("Dream Park is not running")

    def test_the_list_opening_on_another_event_gets_dream_park_tapped(self):
        self.show(EVENT_LIST)
        self.assertPressed(daily.DREAM_PARK)

    def test_the_park_visit_has_its_own_time_from_when_it_starts(self):
        self.tick(daily.RUN_SECONDS - 1)
        self.show(PARK_VIEW)
        self.tick(daily.PARK_SECONDS - 1)
        self.show(PARK_VIEW)
        self.assertEqual(0, self.task.disabled)
        self.tick()
        self.show(PARK_VIEW)
        self.assertStopped("the Dream Park visit ran for 10 minutes")


class TestWholeVisit(Park):

    def test_one_round_from_the_lobby_to_the_lobby(self):
        """The live order: the list opens on another event, the park on Rank 5, one upgrade, nothing to claim."""
        after = edited(FACILITIES, ("Lv.29/50", "Lv.30/50"), ("29/36", "30/36"), ("99.21K", "2.10K"), ("6.37K", "7.64K"))
        hold = daily.NAV_WAIT + 1
        self.run_screens([LOBBY, MENU, EVENT_LIST, PAGE, PARK_VIEW, MANAGE_RANK5, FACILITIES] + [after] * hold + [PARK_VIEW, PAGE]
                         + [(CHRONICLES, NONE_READY)] * (daily.SETTLE + 1) + [(MANAGEMENT, NONE_READY)] * hold + [PAGE, LOBBY])
        self.assertPressed(daily.MENU, daily.EVENT, daily.DREAM_PARK, daily.ENTER_PARK, daily.PARK_MANAGE, daily.PARK_OPERATE, daily.UPGRADE,
                           daily.PANEL_CLOSE, daily.PARK_LEAVE, daily.PARK_ACHIEVEMENTS, daily.MANAGEMENT_TAB, daily.ACHIEVEMENTS_LEAVE,
                           daily.PAGE_LEAVE)
        self.assertParkNothingForbidden()
        self.assertStopped("Daily finished: mail claimed; Dream Park: 1 upgrade, 0 achievement claims (upgrades ended: the next upgrade, "
                           "Tagada, costs more than the profit)")

    def test_a_rank_up_round(self):
        """Every emotion at 36: Manage, the Rank, Rank Up on the blue pill, its result, the grey caption left, then the new targets."""
        targets = edited(FACILITIES_DONE, ("61/36", "61/43"), ("36/36", "36/43"), ("36 /36", "36/43"), ("10.82K", "17.44K"))
        merry = edited(targets, ("Lv.36/50", "Lv.37/50", 0.934), ("36/43", "37/43", 0.803), ("17.44K", "10.75K"), ("6.69K", "8.03K"))
        self.park()["phase"] = daily.TO_OPERATE
        self.run_screens([FACILITIES_DONE, MANAGE, (RANK_READY, LIVE_RANK6), RANK_RESULT, (RANK_AFTER, GREY_AFTER), MANAGE_RANK6, targets]
                         + [merry] * (daily.NAV_WAIT + 1))
        merry_upgrade = (0.772, 0.456)
        expected = [POINTS[target] for target in (daily.PARK_MANAGE, daily.PARK_RANK, daily.RANK_UP, daily.RANK_RESULT_CLOSE, daily.RANK_CLOSE,
                                                  daily.PARK_OPERATE)] + [merry_upgrade, POINTS[daily.PANEL_CLOSE]]
        self.assertEqual(len(expected), len(self.task.clicks), self.task.clicks)
        for (x, y), (expected_x, expected_y) in zip(self.task.clicks, expected):
            self.assertAlmostEqual(expected_x, x, delta=0.005)
            self.assertAlmostEqual(expected_y, y, delta=0.005)
        self.assertEqual(1, self.park()["rank_ups"])
        self.assertEqual([5, 6], self.park()["ranks"])
        self.assertParkNothingForbidden()
