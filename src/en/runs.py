"""What the fork's modes share about a run: how one stops with a message, and what a mode forgets between runs."""

from src.en.notify import announce


def stop(task, message):
    """Announce why a mode stops and stop it, pressing nothing more.

    Args:
        task: The running mode.
        message: The line to show.

    Returns:
        True, which claims the frame.
    """
    announce(task, message)
    task.disable()
    return True


def forgetting(names, method):
    """Wrap a task method so it first drops what a run kept on the task.

    Args:
        names: The attributes to drop from the task, each only when present.
        method: The unbound method being replaced, such as `BaseTask.disable`.

    Returns:
        The replacement.
    """
    def forgetting_run(self):
        for name in names:
            vars(self).pop(name, None)
        return method(self)

    return forgetting_run
