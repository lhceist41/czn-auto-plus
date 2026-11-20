"""Check that the Trauma Center pays Credits only while healing is on.

Upstream's heal switch only gates the Mental Breakdown screen, whose title the catalog never produces, while the
Trauma Center's title it does. So with healing off a run could still reach the Trauma Center and pay there.
"""

import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

# The real module, so the check fails if upstream stops recognising the Trauma Center the way `heal.py` reads it.
import utils_chaos  # noqa: E402

from src.en import heal  # noqa: E402
from src.en.handlers import standing_in  # noqa: E402
from tests.fakes import HEIGHT, WIDTH, FakeBox  # noqa: E402


class FakeTask:
    """A Chaos run on the Trauma Center, holding no Communication Pass."""

    def __init__(self):
        self.name = "自动卡厄思模式"
        self.width, self.height = WIDTH, HEIGHT
        self.all_texts = [FakeBox(heal.TITLE, *heal.TITLE_POINT)]
        self.logged = []
        self.notifications = []
        self.disabled = False

    def ocr(self, *region):
        return [types.SimpleNamespace(name="0")]

    def sleep(self, seconds):
        pass

    def log_info(self, message, notify=False):
        self.logged.append(message)

    def notification(self, message, title=None, error=False, tray=False, **kwargs):
        self.notifications.append(message)

    def disable(self):
        self.disabled = True


def visit(healing, nobody_recovering=False):
    """Run upstream's Trauma Center handler, as the fork wraps it, with the heal switch set.

    Args:
        healing: The heal switch.
        nobody_recovering: Whether the screen says nobody is in treatment.

    Returns:
        The task, the handler's answer and the points it clicked.
    """
    task = FakeTask()
    if nobody_recovering:
        task.all_texts.append(FakeBox(heal.NOBODY_RECOVERING, 0.5, 0.5))
    clicks = []
    settings = {heal.HEALING: healing}
    with standing_in(utils_chaos, _get_config_value=lambda task_, key, default: settings.get(key, default),
                     _get_game_text=lambda task_, text: text, _move_and_click=lambda task_, x, y: clicks.append((x, y))):
        answer = heal.paying_credits(utils_chaos.handle_trauma_center, utils_chaos)(task)
    return task, answer, clicks


class TestHeal(unittest.TestCase):

    def test_the_epione_center_stops_the_run_when_healing_is_off(self):
        task, answer, clicks = visit(healing=False)
        self.assertIs(True, answer)
        self.assertEqual([], clicks)
        self.assertTrue(task.disabled)
        self.assertEqual(["Stopped at the Epione Center: healing is off. Treat the combatant yourself, then press Start again."],
                         task.notifications)

    def test_the_epione_center_pays_credits_when_healing_is_on(self):
        task, answer, clicks = visit(healing=True)
        self.assertIs(True, answer)
        self.assertFalse(task.disabled)
        self.assertEqual([(0.420, 0.339), (0.702, 0.924)], clicks, "opens the combatant, then pays Credits")

    def test_an_empty_epione_center_is_left_to_upstream(self):
        """Upstream only taps back there, so stopping would end a run for nothing."""
        task, answer, clicks = visit(healing=False, nobody_recovering=True)
        self.assertIs(True, answer)
        self.assertFalse(task.disabled)
        self.assertEqual([], task.notifications)
        self.assertEqual([(0.044, 0.046)], clicks, "the back tap")

    def test_healing_off_leaves_every_other_screen_to_upstream(self):
        task = FakeTask()
        task.all_texts = []
        with standing_in(utils_chaos, _get_config_value=lambda task_, key, default: False if key == heal.HEALING else default):
            self.assertIs(False, heal.paying_credits(utils_chaos.handle_trauma_center, utils_chaos)(task))
        self.assertFalse(task.disabled)


if __name__ == "__main__":
    unittest.main()
