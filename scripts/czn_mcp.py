# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp==2.3.0"]
# ///
"""MCP server giving Claude a debug run's screen, OCR, settings and clicks.

Claude Code starts this with `uv run --script` (see `.mcp.json`), so `mcp` lives in uv's own environment. Installed
into the app's Python it would upgrade starlette past what FastAPI accepts. Each tool forwards to `src/en/remote.py`,
which only a `main_debug.py` run serves.
"""

import base64
import contextlib
import http.client
import json
import threading
import time
import urllib.error
import urllib.request

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# Where `src/en/remote.py` listens.
URL = "http://127.0.0.1:47821"
# Seconds to wait for a reply. Above the remote's own 15 s wait for the page loop, so its clearer error arrives first.
TIMEOUT = 30
# Most bytes of a refused request's text to show. The port's own refusals are one short line.
REFUSAL_LIMIT = 4096
# Seconds between pings, which keep "MCP connected" in the app's title. Below the remote's `STALE`.
HEARTBEAT = 5

server = MCPServer(
    "czn",
    instructions="Drives a running `python main_debug.py` session of the CZN bot. Coordinates are fractions of the 16:9 game frame. "
                 "Hold the bot before clicking through screens yourself, and release it afterwards.",
)


def call(command, **kwargs):
    """Send one command to the debug run and return its result.

    Args:
        command: The remote command name, one of `remote.COMMANDS`.
        **kwargs: The command's arguments.

    Returns:
        The command's result, decoded from JSON.

    Raises:
        ToolError: The debug run is not answering, refused the request, broke off or garbled its reply, or the
            command failed there. Any other exception reaches Claude as a bare "Error executing tool", without its
            message.
    """
    request = urllib.request.Request(f"{URL}/{command}", data=json.dumps(kwargs).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            reply = json.load(response)
    except urllib.error.HTTPError as error:
        text = refusal(error)
        status = f"HTTP {error.code} {error.reason}".rstrip()
        raise ToolError(f"the debug run answered {command} with {status}{text}") from error
    except urllib.error.URLError as error:
        raise ToolError(f"nothing answering on {URL} - start `python main_debug.py` first ({error.reason})") from error
    # `urlopen` wraps only a failure to connect or send in `URLError`; these come after the request went out.
    except TimeoutError as error:
        raise ToolError(f"the debug run accepted {command} but then sent nothing for {TIMEOUT} s") from error
    except (ConnectionError, http.client.IncompleteRead) as error:
        raise ToolError(f"the debug run hung up on {command} before its reply was complete ({error})") from error
    except http.client.HTTPException as error:
        raise ToolError(f"the debug run answered {command} with something that is not HTTP "
                        f"({type(error).__name__}: {error})") from error
    # Besides `JSONDecodeError`, `json.load` raises a plain `ValueError` for an integer past Python's digit limit and
    # `RecursionError` for nesting past the recursion limit.
    except (ValueError, RecursionError) as error:
        raise ToolError(f"the debug run answered {command} with a reply that is not valid JSON ({error})") from error
    except OSError as error:
        raise ToolError(f"the debug run's reply to {command} could not be read ({error})") from error
    if not isinstance(reply, dict) or "ok" not in reply or ("result" if reply["ok"] else "error") not in reply:
        raise ToolError(f"the debug run answered {command} with JSON that is not a reply: {json.dumps(reply)[:200]}")
    if not reply["ok"]:
        raise ToolError(reply["error"])
    return reply["result"]


def refusal(error):
    """Return the text an HTTP error came with, as `": <text>"`, or nothing when it has none worth showing.

    One socket read for a body sent with a Content-Length or none, so a body that trickles or never comes costs one
    `TIMEOUT`, not one per byte. A chunked body has its size line read whole first, which a peer can stretch.

    Args:
        error: The `urllib.error.HTTPError` raised for the reply.

    Returns:
        The text, or an empty string for an empty, non-text or unreadable body.
    """
    with error:
        # Whatever goes wrong here, the status alone must still reach Claude as a `ToolError`.
        try:
            if not error.headers.get_content_type().startswith("text/"):
                return ""
            text = error.read1(REFUSAL_LIMIT).decode(error.headers.get_content_charset() or "utf-8", "replace").strip()
        except Exception:
            return ""
    return f": {text}" if text else ""


def ping():
    """Tell the debug run this bridge is alive, for as long as Claude Code keeps it open. Any failure is ignored, so the pings never stop."""
    while True:
        with contextlib.suppress(Exception):
            call("status")
        time.sleep(HEARTBEAT)


@server.tool()
def status() -> dict:
    """Which task is running, whether the bot is held, which tasks are switched on, and the app's process id."""
    return call("status")


@server.tool()
def screenshot() -> Image:
    """The game frame the bot last read, as a JPEG."""
    return Image(data=base64.b64decode(call("screenshot")["jpeg"]), format="jpeg")


@server.tool()
def texts() -> list:
    """Every text the running mode read on its last frame, with its centre as fractions of the frame."""
    return call("texts")


@server.tool()
def click(x: float, y: float) -> str:
    """Click a point, given as fractions of the frame from 0 to 1. Runs between the bot's frames, so it never races a handler."""
    return call("click", x=x, y=y)


@server.tool()
def drag(x1: float, y1: float, x2: float, y2: float) -> str:
    """Press at (x1, y1), move to (x2, y2) and let go, as fractions of the frame from 0 to 1, such as a card a tutorial
    asks to slide. The release lands 95% of the way along, so aim a little past the target. Needs the app's PostMessage
    interaction: under any other the drag is refused."""
    return call("drag", x1=x1, y1=y1, x2=x2, y2=y2)


@server.tool()
def press_key(key: str) -> str:
    """Press a key in the game, such as `esc`."""
    return call("press_key", key=key)


@server.tool()
def hold(on: bool = True) -> dict:
    """Hold the bot so it stops acting on frames, or release it with `on=False`. A held bot still reads every frame.
    A hold replies once the bot's own clicks have stopped, with `taken: true`. With `taken: false` the page loop did not
    come round in 15 s (the `reason` says why): the bot stays held, but a click it had decided on may still land, so
    take a screenshot before acting."""
    return call("hold", on=on)


@server.tool()
def settings(task: str = "ChaosMode") -> dict:
    """Every setting a task carries, by its config key."""
    return call("settings", task=task)


@server.tool()
def set_setting(key: str, value: str | int | float | bool | list[str], task: str = "ChaosMode") -> str | int | float | bool | list[str]:
    """Change one setting, saved as the settings card would. Upstream's keys are Chinese, so read `settings` for the exact key."""
    return call("set_setting", key=key, value=value, task=task)


@server.tool()
def set_running(task: str, running: bool) -> dict:
    """Start or stop a mode such as `ChaosMode`, as its Start and Stop buttons would. Hold the bot first to start it idle."""
    return call("set_running", task=task, running=running)


@server.tool()
def quit() -> dict:
    """End the whole app, not just a mode. Refused while a mode runs: stop it with `set_running` first. Replies with the
    app's `pid` before it exits; wait until that process is gone before starting the app again."""
    return call("quit")


if __name__ == "__main__":
    threading.Thread(target=ping, name="ping", daemon=True).start()
    server.run()
