"""How big the window opens, and how it divides its height. Arithmetic only.

Both rules here were wrong in the same way: a number chosen for one screen and
then applied to every screen.

The window asked for 1280x860 whatever display it opened on. A 1366x768
laptop - still the commonest screen this runs on - has about 730 usable pixels
of height once the title bar and taskbar are out, so the bottom 130 went under
the taskbar: the readiness line, and on the models screen the button that
applies the whole selection. Nothing was broken and nothing down there could be
clicked either, because it was not on the screen.

The activity log asked for eight lines the same way. Eight lines is a fifth of
a desktop window and a third of a laptop one; left fixed, it took so much of a
648-pixel window that the list of twenty-five models underneath had four pixels
to show them in.

No Tk here: a layout rule that can only be checked by opening a window is a
layout rule nobody checks.
"""
from __future__ import annotations

#: What the window opens at when the screen has room for it.
PREFERRED_SIZE = (1280, 860)
#: Below which it will not go, matching the shell's own minsize.
MINIMUM_SIZE = (880, 560)
#: Room the desktop keeps for itself: a title bar above, a taskbar below.
SCREEN_MARGIN = (80, 120)

#: The activity log never shrinks below the first and never grows past the
#: second, whatever the window does.
ACTIVITY_LINES = (3, 8)
#: Window heights those two map to. A desktop window keeps all eight lines; a
#: laptop one gives the difference back to the page.
ACTIVITY_RANGE = (560, 860)


def fitted_size(screen, preferred=PREFERRED_SIZE, minimum=MINIMUM_SIZE,
                margin=SCREEN_MARGIN):
    """The size to open at on a screen this big, and never larger than it.

    The minimum wins over the margin. A window smaller than its own minimum
    would be resized back up by Tk anyway, and the clamp would have achieved
    nothing except a worse position.
    """
    width = max(minimum[0], min(preferred[0], screen[0] - margin[0]))
    height = max(minimum[1], min(preferred[1], screen[1] - margin[1]))
    return width, height


def centred_geometry(size, screen):
    """A Tk geometry string placing ``size`` in the middle of ``screen``.

    Never negative: a window wider than the screen would otherwise be placed
    off the left edge, where its title bar cannot be grabbed to drag it back.
    """
    width, height = size
    x = max(0, (screen[0] - width) // 2)
    y = max(0, (screen[1] - height) // 3)      # a third down reads as centred
    return '%dx%d+%d+%d' % (width, height, x, y)


def activity_lines(height, lines=ACTIVITY_LINES, span=ACTIVITY_RANGE):
    """How many lines of log a window this tall can afford."""
    low, high = span
    if height >= high:
        return lines[1]
    if height <= low:
        return lines[0]
    share = (height - low) / float(high - low)
    return int(round(lines[0] + share * (lines[1] - lines[0])))


__all__ = ['PREFERRED_SIZE', 'MINIMUM_SIZE', 'SCREEN_MARGIN',
           'ACTIVITY_LINES', 'ACTIVITY_RANGE',
           'fitted_size', 'centred_geometry', 'activity_lines']
