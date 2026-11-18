"""Game Language as one row under App Config on the Settings page instead of a row on every mode's card.

Upstream keeps the language in each mode's own config and reads it through `utils._get_game_language`, so the user sets it
once per mode and Story, which declares none, always reads Simplified. Every mode now reads the Settings page value instead.
"""

from ok import ConfigOption, Logger, og

from src.en.framework import import_ui
from src.en.handlers import loaded, register, wrap

logger = Logger.get_logger(__name__)

# The mode config key upstream reads. Hidden from the mode cards, which `overrides.py` reshapes.
MODE_KEY = "游戏语言"
# The choices, as upstream spells them. English behaves like Simplified, since `_get_game_text` falls back to the
# untranslated literal when a language has no map file.
ENGLISH = "English"
GAME_LANGUAGES = [ENGLISH, "简体中文", "繁体中文"]
# The row's label, and the key it is saved under.
LABEL = "Game Language"
# The line under the label.
DESCRIPTION = "The language the game itself shows, so the bot can read its screens. Use English for the Global client."
# The framework's own Language row, renamed so the two rows read apart.
APP_LABEL = "App Language"
APP_DESCRIPTION = "The language of this app's menus and settings."
# The file under `configs/` the choice is saved to. The leading underscore keeps the Settings page from giving it a section of
# its own, since the row is placed under App Config instead.
CONFIG_NAME = "_game_language"
# Marks the reader swap in `handlers.wrap`, so it is installed once.
TAG = "game_language"

# Listed in `global_configs`, which is what puts it on the Settings page.
language_option = ConfigOption(CONFIG_NAME, {LABEL: ENGLISH}, config_description={LABEL: DESCRIPTION},
                               config_type={LABEL: {"type": "drop_down", "options": GAME_LANGUAGES}})

_patched = False


def current():
    """Read the language picked on the Settings page.

    Returns:
        One of `GAME_LANGUAGES`, or English before the global config exists.
    """
    try:
        return str(og.global_config.get_config(language_option).get(LABEL, ENGLISH)).strip() or ENGLISH
    except Exception:
        return ENGLISH


def reading_the_setting(original):
    """Build the replacement for `utils._get_game_language`.

    Args:
        original: Upstream's reader, which looked at the mode's own config. Unused.

    Returns:
        A reader that ignores the task and answers from the Settings page.
    """
    def _get_game_language(task):
        return current()

    return _get_game_language


def with_game_language(original):
    """Build the replacement for the Settings page's App Config builder.

    Args:
        original: The framework's `SettingsPage._add_appearance`.

    Returns:
        A builder that also renames the Language row and puts Game Language under it.
    """
    def _add_appearance(page):
        original(page)
        try:
            add_language_rows(page)
        except Exception as error:
            logger.warning(f"could not add Game Language under App Config: {error}")

    return _add_appearance


def add_language_rows(page):
    """Rename the app's Language row and add the Game Language row directly below it.

    Args:
        page: The Settings page, right after its App Config group is built.
    """
    group, row_class = import_ui("kit.cards", "SettingGroup"), import_ui("kit.cards", "SettingRow")
    editor = import_ui("tasks.config_editors", "DropDownEditor")
    card = page.appearance_section.findChild(group)
    app_row = next(row for row in card.findChildren(row_class) if row.isAncestorOf(page.language_combo))
    app_row.title_label.setText(og.app.tr(APP_LABEL))
    app_row.description_label.setText(og.app.tr(APP_DESCRIPTION))
    # The Language row is the group's last, so a new row lands right under it.
    card.add_row(editor(language_option.config_description, GAME_LANGUAGES, og.global_config.get_config(language_option), LABEL))


def install():
    """Point the language reader at the Settings page once `utils` is loaded."""
    utils = loaded("utils")
    if utils is not None:
        wrap(utils, "_get_game_language", reading_the_setting, TAG)


def apply():
    """Have every mode read Game Language from the Settings page."""
    global _patched
    if _patched:
        return
    register(install)
    page = import_ui("settings.settings_page", "SettingsPage")
    if page is not None:
        page._add_appearance = with_game_language(page._add_appearance)
    _patched = True
    logger.info("game language read from the Settings page")
