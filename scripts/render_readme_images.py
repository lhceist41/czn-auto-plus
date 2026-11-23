"""Render the README's app images from the real widgets, with no game and none of your own settings.

Builds the four modes and the Tasks page the way the app does, then opens the card removal picker the way a
settings row does, in the dark theme with English labels from `i18n/`. Every setting comes from the modes'
defaults in a temporary config folder, so nothing under `configs/` is read or written.

Usage:
    python scripts/render_readme_images.py [--out FOLDER]
"""

import argparse
import gettext
import shutil
import sys
import tempfile
import types
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ok_tasks"))

# The Tasks page's size, tall enough to reach the folded sections under the everyday settings.
PAGE_SIZE = (1200, 1250)
# The mode selected on the Tasks page, and the setting whose picker is shown.
SELECTED_MODE = "ChaosMode"
PICKED_SETTING = "移除卡牌列表"
# The card the picker image hovers. Any card with effect text works; this one has a short one.
HOVERED_CARD = "Absolute Protection"
# Qt wraps a rich-text tooltip at about this width.
TOOLTIP_WIDTH = 300
# Every widget built here, held until `main` deletes them all at once. Letting Python collect one whose Qt parent is already gone crashes the process.
KEPT = []


class CatalogApp:
    """Stands in for the running app's translator, reading the same English catalog it ships."""

    def __init__(self):
        self.catalog = gettext.translation("ok", str(REPO_ROOT / "i18n"), languages=["en_US"])

    def tr(self, key):
        """Translate one label the way the app does.

        Args:
            key: The string being translated.

        Returns:
            Its English text, or the key when the catalog has none.
        """
        return self.catalog.gettext(key) if key else key


class Executor:
    """Holds the task lists the Tasks page reads, and nothing else of the real executor."""

    def __init__(self, tasks):
        self.trigger_tasks = list(tasks)
        self.onetime_tasks = []
        self.scene = None

    def get_all_tasks(self):
        """List every task the Tasks page shows.

        Returns:
            The one-time tasks, then the modes.
        """
        return self.onetime_tasks + self.trigger_tasks

    def waiting_for_task(self, task):
        """Say which task a queued task waits for, as the Tasks page asks.

        Args:
            task: The task being asked about.

        Returns:
            None, since nothing is queued here.
        """
        return None


def build_modes(executor):
    """Build the four modes, re-shaped and loaded the way the app's task setup does.

    Args:
        executor: The executor the modes are built for.

    Returns:
        The modes, in the order the app lists them.
    """
    from ChaosMode import ChaosMode
    from SortieMode import SortieMode
    from StoryMode import StoryMode

    from src.en.daily import DailyMode

    modes = []
    for mode_class in (DailyMode, ChaosMode, SortieMode, StoryMode):
        mode = mode_class(executor, None)
        # The task manager marks what it loads out of `ok_tasks/` before `load_config`, and `overrides` replaces
        # only those modes' Instructions. `shell.restructure` clears the mark again, as in the app.
        if mode_class is not DailyMode:
            mode.is_custom = True
        mode.load_config()
        modes.append(mode)
    return modes


def apply_ui_patches():
    """Apply the fork's patches that change how the Tasks page and its forms look, as `src/globals.py` does."""
    from src.en import dashboard, forms, game_language, kept_forms, overrides, picker, sections, task_list, upload

    # `upload` also takes the Configuration row off every mode, and refuses the config upload that row offered.
    for module in (sections, forms, task_list, kept_forms, picker, dashboard, overrides, game_language, upload):
        module.apply()


def render_tasks_page(out_folder):
    """Save the Tasks page with the selected mode's settings open.

    Args:
        out_folder: Where the image goes.

    Returns:
        The modes, for the picker.
    """
    from ok import og
    from ok.ui.qt.kit.theme import theme

    from src.en import shell
    from src.en.framework import import_ui

    executor = Executor([])
    modes = build_modes(executor)
    executor.trigger_tasks = list(modes)
    og.executor = executor
    og.task_manager = types.SimpleNamespace(has_custom=False, imported_scripts={})
    shell.restructure(executor, og.task_manager, import_ui("Communicate", "communicate"))

    page = import_ui("tasks.tasks_page", "TasksPage")()
    page.timer.stop()
    # Laid out at its final size before the form is built, or the rows keep heights measured for another width and cut their text.
    grab(page, PAGE_SIZE)
    page.select_task(next(mode for mode in modes if mode.__class__.__name__ == SELECTED_MODE))
    page.setAutoFillBackground(True)
    palette = page.palette()
    palette.setColor(page.backgroundRole(), theme.color("window"))
    page.setPalette(palette)
    save(page, PAGE_SIZE, out_folder / "tasks_page.png")
    KEPT.append(page)
    return modes


def render_picker(out_folder, modes):
    """Save the card removal picker, opened the way its settings row opens it, with one card hovered.

    Args:
        out_folder: Where the image goes.
        modes: The modes built for the Tasks page.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QLabel, QWidget

    from ok.ui.qt.kit.theme import theme

    from src.en.framework import import_ui

    chaos = next(mode for mode in modes if mode.__class__.__name__ == SELECTED_MODE)
    list_editor = import_ui("tasks.config_editors", "ListEditor")
    dialog_class = import_ui("tasks.ModifyListDialog", "ModifyListDialog")
    window = QWidget()
    window.resize(*PAGE_SIZE)
    opened = {}
    original_exec = dialog_class.exec
    # The row builds the dialog and then blocks on exec, so it is caught there.
    dialog_class.exec = lambda dialog: opened.setdefault("dialog", dialog)
    try:
        row = list_editor(chaos.config_description, {PICKED_SETTING: list(chaos.config[PICKED_SETTING])}, PICKED_SETTING,
                          options_available=chaos.config_type[PICKED_SETTING]["options_available"])
        row.setParent(window)
        row.open_dialog()
    finally:
        dialog_class.exec = original_exec
    dialog = opened["dialog"]
    panel = dialog.panel
    panel.adjustSize()

    # A tooltip is its own window, so it never shows in a grab. It is drawn from the row's own text in the theme's tooltip style instead.
    view = dialog.option_list
    item = next(view.item(index) for index in range(view.count()) if view.item(index).text() == HOVERED_CARD)
    view.scrollToItem(item)
    image = grab(panel, (panel.width(), panel.sizeHint().height()))
    tip = QLabel(item.toolTip())
    tip.setTextFormat(Qt.TextFormat.RichText)
    tip.setWordWrap(True)
    tip.setFixedWidth(TOOLTIP_WIDTH)
    tip.setStyleSheet(f"QLabel {{ color: {theme.color('text').name()}; background: {theme.color('surface_alt').name()};"
                      f" border: 1px solid {theme.color('border_strong').name()}; border-radius: 6px; padding: 4px 8px; }}")
    tip.adjustSize()
    tip_image = grab(tip, (tip.width(), tip.height()))
    rect = view.visualItemRect(item)
    corner = view.viewport().mapTo(panel, rect.center()) + QPoint(24, 14)
    corner.setX(min(corner.x(), image.width() - tip_image.width() - 8))
    painter = QPainter(image)
    painter.drawPixmap(corner, tip_image)
    painter.end()
    image.save(str(out_folder / "option_picker.png"))
    print(f"saved {out_folder / 'option_picker.png'} ({image.width()}x{image.height()})")
    KEPT.extend((window, row, dialog, tip))


def grab(widget, size):
    """Lay out a widget off screen at a size and grab it.

    Args:
        widget: The widget to draw.
        size: Its width and height in pixels.

    Returns:
        The drawn `QPixmap`.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.resize(*size)
    widget.show()
    for _ in range(3):
        QApplication.processEvents()
    return widget.grab()


def save(widget, size, path):
    """Grab a widget and save it as a PNG.

    Args:
        widget: The widget to draw.
        size: Its width and height in pixels.
        path: The file to write.
    """
    image = grab(widget, size)
    image.save(str(path))
    print(f"saved {path} ({image.width()}x{image.height()})")


def main():
    """Render both README images into the folder `--out` names."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "images", help="folder the PNGs are written to")
    out_folder = parser.parse_args().out.resolve()
    out_folder.mkdir(parents=True, exist_ok=True)

    import shiboken6
    from PySide6.QtWidgets import QApplication

    from ok import og
    from ok.ui.qt.kit.theme import Theme, theme
    from ok.util.config import Config

    app = QApplication.instance() or QApplication(sys.argv)
    config_folder = tempfile.mkdtemp(prefix="readme-render-")
    # Set before anything builds a `Config`, so every mode and page saves into the temporary folder.
    Config.config_folder = config_folder
    og.app = CatalogApp()
    og.config = {}
    # `forms` hides some Settings page rows. The page is not drawn here, so a stand-in that accepts the edit is enough.
    og.global_config = types.SimpleNamespace(config_options=defaultdict(lambda: types.SimpleNamespace(config_type={})),
                                             get_config=lambda section: {})
    theme.set_theme(Theme.DARK)
    try:
        apply_ui_patches()
        modes = render_tasks_page(out_folder)
        render_picker(out_folder, modes)
    finally:
        shutil.rmtree(config_folder, ignore_errors=True)
    # Deleted here, as the tests do, because a kit widget still alive when the interpreter exits crashes the process.
    for widget in QApplication.topLevelWidgets():
        if shiboken6.isValid(widget):
            shiboken6.delete(widget)
    KEPT.clear()


if __name__ == "__main__":
    main()
