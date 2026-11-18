"""Recognise the route screen by the minimap's location pin instead of its zoom icon.

Upstream knows the route screen only by the zoom-in icon on the minimap's corner, just below where the party stands. A
combatant's sprite or the floor glow can cover it enough to miss, and the run then sits on the route screen tapping
stray event matches. The location pin sits inside the minimap, where nothing is drawn over it.
"""

from src.en.handlers import loaded, register, standing_in, wrap

# Names this change in the shared record of what a function already carries, so it is applied once.
TAG = "the minimap pin marks the route screen"
# The zoom-in icon upstream looks for, and the zoom-out icon the expanded map shows in its place.
ICON = "position"
EXPANDED_MAP = "minimizemap"
# The minimap's location pin, and the region `recognize_map_connections` reads the minimap from.
PIN = "position_in_map"
MINIMAP = (0.019, 0.633, 0.380, 0.972)
# Over the 853 frames in `captures/`, every route screen scored 0.905-0.987 and nothing else went above 0.716. The zoom
# icon scored 0.60-0.75 on three of those route screens.
PIN_THRESHOLD = 0.85

_patched = False


def finding_the_pin(task, find_feature):
    """Build a `find_feature` that answers the zoom-icon search with the minimap's location pin.

    Args:
        task: The running task, for `box_of_screen`.
        find_feature: The task's own `find_feature`, which every other search passes straight through to.

    Returns:
        The stand-in `find_feature`.
    """
    def find(*args, **kwargs):
        if kwargs.get("feature_name") != ICON:
            return find_feature(*args, **kwargs)
        pins = find_feature(feature_name=PIN, box=task.box_of_screen(*MINIMAP), threshold=PIN_THRESHOLD)
        # The expanded map draws the pin too, and `handle_minimizemap` closes it further down the list.
        if pins and find_feature(feature_name=EXPANDED_MAP):
            return []
        return pins

    return find


def reading_the_pin(original):
    """Wrap `handle_route_selection` so its route-screen check reads the minimap's location pin.

    Args:
        original: The handler currently installed.

    Returns:
        The wrapped handler.
    """
    def handle_route_selection(task):
        with standing_in(task, find_feature=finding_the_pin(task, task.find_feature)):
            return original(task)

    return handle_route_selection


def install(utils):
    """Put the pin check on `handle_route_selection` wherever it is registered.

    Args:
        utils: Upstream's `utils` module, or None when it has not been imported yet.
    """
    if utils is not None:
        wrap(utils, "handle_route_selection", reading_the_pin, TAG)


def apply():
    """Put the pin check on `handle_route_selection` once the modes are loaded."""
    global _patched
    if _patched:
        return
    register(lambda: install(loaded("utils")))
    _patched = True
