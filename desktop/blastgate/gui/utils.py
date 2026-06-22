"""
GUI utility functions for Blastgate

This module provides helper functions for:
- UI scaling and font configuration
- Window centering
- Color manipulation (hex/rgb conversion, interpolation)
- Canvas drawing (rounded rectangles)
- User-friendly error message display
"""
import logging
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox
from typing import Tuple, Optional

from ..utils.errors import get_error_info, format_error_message, parse_hub_error
from ..exceptions import HubCommandError, HubOfflineError, NetworkError

logger = logging.getLogger(__name__)


def apply_ui_scale(root: tk.Misc, scale: float = 1.30) -> None:
    """
    Apply UI scaling to tkinter root widget.

    Adjusts tk scaling and font sizes based on scale factor.
    Handles errors gracefully (non-critical UI operation).

    Args:
        root: Tkinter root widget or any tk.Misc widget
        scale: Scale factor (default 1.30, range 0.5-3.0)

    Example:
        >>> app = tk.Tk()
        >>> apply_ui_scale(app, 1.5)
    """
    try:
        root.tk.call("tk", "scaling", float(scale))
        logger.debug("Applied tk scaling: %.2f", scale)
    except (tk.TclError, AttributeError) as e:
        logger.debug("Failed to set tk scaling: %s", e)

    try:
        # Configure standard fonts
        default_font = tkfont.nametofont("TkDefaultFont")
        text_font = tkfont.nametofont("TkTextFont")
        fixed_font = tkfont.nametofont("TkFixedFont")

        base_size = max(10, int(round(10 * float(scale))))

        for font in (default_font, text_font, fixed_font):
            try:
                font.configure(size=base_size)
            except (tk.TclError, AttributeError) as e:
                logger.debug("Failed to configure font: %s", e)

        # Configure heading font
        try:
            heading = tkfont.Font(name="TkHeadingFont", exists=True)
            heading_size = max(12, int(round(13 * float(scale))))
            heading.configure(size=heading_size, weight="bold")
            logger.debug("Configured fonts: base=%d, heading=%d", base_size, heading_size)
        except (tk.TclError, AttributeError) as e:
            logger.debug("Failed to configure heading font: %s", e)

    except Exception as e:
        logger.warning("Font configuration failed: %s", e)


def smart_center(win: tk.Toplevel, w: int, h: int, scale: float = 1.0) -> None:
    """
    Center a window on screen with fallback for errors.

    Args:
        win: Toplevel window to center
        w: Base window width (will be scaled)
        h: Base window height (will be scaled)
        scale: UI scale factor (default 1.0, typically 1.0-1.5)

    Example:
        >>> dialog = tk.Toplevel()
        >>> smart_center(dialog, 400, 300, scale=1.3)
    """
    # Apply scale to dimensions
    scaled_w = int(w * scale)
    scaled_h = int(h * scale)

    try:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()

        # Clamp to screen size with margin
        max_w = int(sw * 0.95)
        max_h = int(sh * 0.90)
        final_w = min(scaled_w, max_w)
        final_h = min(scaled_h, max_h)

        x = max(0, (sw - final_w) // 2)
        y = max(0, (sh - final_h) // 2)
        win.geometry(f"{final_w}x{final_h}+{x}+{y}")
        logger.debug("Centered window: %dx%d (scale=%.2f) at (%d,%d)", final_w, final_h, scale, x, y)
    except (tk.TclError, AttributeError) as e:
        logger.debug("Failed to center window, using default: %s", e)
        try:
            win.geometry(f"{scaled_w}x{scaled_h}")
        except (tk.TclError, AttributeError) as e2:
            logger.warning("Failed to set window geometry: %s", e2)


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """
    Convert hex color string to RGB tuple.

    Args:
        hex_color: Hex color string (with or without #)

    Returns:
        RGB tuple (r, g, b) with values 0-255
        Returns (0, 0, 0) for invalid input

    Example:
        >>> hex_to_rgb("#ff5733")
        (255, 87, 51)
        >>> hex_to_rgb("ff5733")
        (255, 87, 51)
    """
    h = (hex_color or "").strip()
    if h.startswith("#"):
        h = h[1:]

    if len(h) != 6:
        logger.debug("Invalid hex color: %s (returning black)", hex_color)
        return (0, 0, 0)

    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError as e:
        logger.debug("Failed to parse hex color %s: %s", hex_color, e)
        return (0, 0, 0)


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    """
    Convert RGB tuple to hex color string.

    Args:
        rgb: RGB tuple (r, g, b) with values 0-255

    Returns:
        Hex color string with # prefix

    Example:
        >>> rgb_to_hex((255, 87, 51))
        '#ff5733'
    """
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp(a: int, b: int, t: float) -> int:
    """
    Linear interpolation between two integers.

    Args:
        a: Start value
        b: End value
        t: Interpolation factor (0.0 = a, 1.0 = b)

    Returns:
        Interpolated integer value

    Example:
        >>> lerp(0, 100, 0.5)
        50
        >>> lerp(10, 20, 0.25)
        12
    """
    return int(round(a + (b - a) * t))


def lerp_color(color1: str, color2: str, t: float) -> str:
    """
    Interpolate between two hex colors.

    Args:
        color1: Start hex color
        color2: End hex color
        t: Interpolation factor (0.0 = color1, 1.0 = color2)

    Returns:
        Interpolated hex color string

    Example:
        >>> lerp_color("#000000", "#ffffff", 0.5)
        '#7f7f7f'
    """
    r1, g1, b1 = hex_to_rgb(color1)
    r2, g2, b2 = hex_to_rgb(color2)

    r = lerp(r1, r2, t)
    g = lerp(g1, g2, t)
    b = lerp(b1, b2, t)

    return rgb_to_hex((r, g, b))


def draw_rounded_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: int = 18,
    **kwargs
) -> int:
    """
    Draw a rounded rectangle on a Canvas.

    Uses polygon with smooth=True to create rounded corners.

    Args:
        canvas: Canvas widget to draw on
        x1, y1: Top-left corner coordinates
        x2, y2: Bottom-right corner coordinates
        radius: Corner radius in pixels (default 18)
        **kwargs: Additional arguments passed to create_polygon()
                 (fill, outline, width, etc.)

    Returns:
        Canvas item ID of created polygon

    Example:
        >>> canvas = tk.Canvas(root)
        >>> item_id = draw_rounded_rect(canvas, 10, 10, 100, 50,
        ...                             radius=15, fill="#2a9fd6", outline="")
    """
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]

    try:
        return canvas.create_polygon(points, smooth=True, **kwargs)
    except tk.TclError as e:
        logger.warning("Failed to draw rounded rect: %s", e)
        # Fallback: draw regular rectangle
        return canvas.create_rectangle(x1, y1, x2, y2, **kwargs)


def show_user_error(parent: Optional[tk.Misc], error: Exception, context: str = "") -> None:
    """
    Display user-friendly error dialog with troubleshooting steps.

    Automatically detects error type and shows appropriate message
    from the error database with actionable solutions.

    Args:
        parent: Parent widget for dialog (can be None)
        error: Exception that occurred
        context: Additional context about what was being done

    Example:
        >>> try:
        ...     client.set_node_gate("BG-123", "open")
        ... except HubCommandError as e:
        ...     show_user_error(window, e, "Failed to open gate")
    """
    error_key = "unknown_error"
    error_str = str(error)

    # Detect error type
    if isinstance(error, HubOfflineError):
        error_key = "hub_offline"
    elif isinstance(error, NetworkError):
        error_key = "connection_timeout"
    elif isinstance(error, HubCommandError):
        # Parse hub error response
        error_key = parse_hub_error(error_str)
    elif "timeout" in error_str.lower():
        error_key = "connection_timeout"
    elif "wifi" in error_str.lower():
        error_key = "wifi_error"

    # Format message with solutions
    msg = format_error_message(error_key, details=context)

    # Get error info for title
    info = get_error_info(error_key)

    logger.error("User error displayed: %s - %s", info.title, error_str)

    # Show dialog
    messagebox.showerror(
        title=info.title,
        message=msg,
        parent=parent
    )


def add_button_hover_effect(button: tk.Widget, hover_cursor: str = "hand2") -> None:
    """
    Add hover effect to button (cursor change and subtle visual feedback).

    Args:
        button: Button widget to add hover effect to
        hover_cursor: Cursor to show on hover (default: hand2)

    Example:
        >>> btn = ttk.Button(parent, text="Click Me")
        >>> add_button_hover_effect(btn)
    """
    def on_enter(e):
        try:
            button.configure(cursor=hover_cursor)
        except tk.TclError as e:
            logger.debug("Failed to set hover cursor: %s", e)

    def on_leave(e):
        try:
            button.configure(cursor="")
        except tk.TclError as e:
            logger.debug("Failed to reset cursor: %s", e)

    try:
        button.bind("<Enter>", on_enter)
        button.bind("<Leave>", on_leave)
    except tk.TclError as e:
        logger.debug("Failed to bind hover events: %s", e)


def confirm_critical_action(parent: Optional[tk.Misc], title: str, message: str,
                           action_name: str = "Continue") -> bool:
    """
    Show confirmation dialog for critical/destructive actions.

    Args:
        parent: Parent widget for dialog
        title: Dialog title
        message: Warning message explaining the action
        action_name: Name of the action button (default: "Continue")

    Returns:
        True if user confirmed, False if canceled

    Example:
        >>> if confirm_critical_action(window, "Reset Configuration",
        ...     "This will reset all node settings to defaults.\\n\\nContinue?",
        ...     "Reset"):
        ...     # Perform reset
    """
    return messagebox.askyesno(
        title=title,
        message=message,
        parent=parent
    )
