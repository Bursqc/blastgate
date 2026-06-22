"""
Animated dropdown menu component for Blastgate

A custom animated dropdown menu that slides down from the hamburger button
with pill-shaped buttons for Refresh, Settings, and Exit.
"""
import logging
import tkinter as tk
from typing import Callable, Optional, List, Tuple

logger = logging.getLogger(__name__)


class AnimatedDropdown(tk.Toplevel):
    """
    Animated dropdown menu that slides down from trigger button.

    Features:
    - Pill-shaped buttons with rounded corners
    - Smooth slide-down animation
    - Auto-close when clicking outside
    - Hover effects

    Example:
        >>> menu_items = [
        ...     ("Refresh", lambda: print("refresh")),
        ...     ("Settings", lambda: print("settings")),
        ...     ("Exit", lambda: print("exit")),
        ... ]
        >>> dropdown = AnimatedDropdown(parent, items=menu_items)
        >>> dropdown.show(x=100, y=50)
    """

    def __init__(
        self,
        master: tk.Widget,
        items: List[Tuple[str, Callable]],
        width: int = 180,
        item_height: int = 44,
        bg_color: str = "#2a2d32",
        hover_color: str = "#3a3d42",
        text_color: str = "#ffffff",
        border_color: str = "#444444",
        radius: int = 18,
    ):
        """
        Initialize animated dropdown menu.

        Args:
            master: Parent widget
            items: List of (label, callback) tuples for menu items
            width: Menu width in pixels
            item_height: Height of each menu item
            bg_color: Background color
            hover_color: Hover background color
            text_color: Text color
            border_color: Border/outline color
            radius: Corner radius for pill shape
        """
        super().__init__(master)

        self.master_widget = master
        self.items = items
        self.width = width
        self.item_height = item_height
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.text_color = text_color
        self.border_color = border_color
        self.radius = radius

        # Calculate total height
        self.total_height = len(items) * item_height + 16  # padding

        # Configure window
        self.overrideredirect(True)  # Remove window decorations
        self.attributes("-topmost", True)
        self.withdraw()  # Start hidden

        # Set transparent background (Windows)
        try:
            self.attributes("-transparentcolor", "#010101")
            self._transparent_bg = "#010101"
        except tk.TclError:
            self._transparent_bg = self.bg_color

        self.configure(bg=self._transparent_bg)

        # Create canvas for drawing
        self.canvas = tk.Canvas(
            self,
            width=self.width,
            height=self.total_height,
            highlightthickness=0,
            bg=self._transparent_bg,
        )
        self.canvas.pack(fill="both", expand=True)

        # Track button rectangles for click detection
        self._button_rects: List[Tuple[int, int, int, int, Callable]] = []
        self._hover_index: Optional[int] = None

        # Animation state
        self._animating = False
        self._visible = False
        self._target_y = 0
        self._current_height = 0

        # Draw initial state
        self._draw()

        # Bind events
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Leave>", self._on_leave)

        # Close on click outside
        self.bind("<FocusOut>", lambda e: self.after(100, self._check_focus))

        logger.debug("AnimatedDropdown created with %d items", len(items))

    def _draw(self):
        """Draw the dropdown menu."""
        self.canvas.delete("all")
        self._button_rects.clear()

        # Draw background with rounded corners
        self._draw_rounded_rect(
            2, 2,
            self.width - 2,
            self._current_height - 2 if self._current_height > 0 else self.total_height - 2,
            radius=self.radius,
            fill=self.bg_color,
            outline=self.border_color,
        )

        if self._current_height < 10:
            return  # Don't draw items during animation start

        # Draw items
        y_offset = 8
        for i, (label, callback) in enumerate(self.items):
            y1 = y_offset
            y2 = y_offset + self.item_height

            # Skip if outside visible area
            if y2 > self._current_height:
                break

            # Background color (hover effect)
            bg = self.hover_color if self._hover_index == i else self.bg_color

            # Draw pill-shaped button
            self._draw_rounded_rect(
                8, y1,
                self.width - 8, y2,
                radius=self.item_height // 2,
                fill=bg,
                outline="",
            )

            # Draw text
            text_y = (y1 + y2) // 2
            self.canvas.create_text(
                self.width // 2, text_y,
                text=label,
                fill=self.text_color,
                font=("Segoe UI", 11, "bold"),
                anchor="center",
            )

            # Store button rect for click detection
            self._button_rects.append((8, y1, self.width - 8, y2, callback))

            y_offset = y2

    def _draw_rounded_rect(
        self, x1: int, y1: int, x2: int, y2: int,
        radius: int, fill: str, outline: str = ""
    ) -> int:
        """Draw a rounded rectangle on canvas."""
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
            x1 + radius, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, fill=fill, outline=outline)

    def _on_motion(self, event: tk.Event):
        """Handle mouse motion for hover effects."""
        x, y = event.x, event.y
        new_hover = None

        for i, (x1, y1, x2, y2, _) in enumerate(self._button_rects):
            if x1 <= x <= x2 and y1 <= y <= y2:
                new_hover = i
                break

        if new_hover != self._hover_index:
            self._hover_index = new_hover
            self.canvas.configure(cursor="hand2" if new_hover is not None else "")
            self._draw()

    def _on_leave(self, event: tk.Event):
        """Handle mouse leave."""
        if self._hover_index is not None:
            self._hover_index = None
            self.canvas.configure(cursor="")
            self._draw()

    def _on_click(self, event: tk.Event):
        """Handle click on menu item."""
        x, y = event.x, event.y

        for x1, y1, x2, y2, callback in self._button_rects:
            if x1 <= x <= x2 and y1 <= y <= y2:
                self.hide()
                if callable(callback):
                    try:
                        callback()
                    except Exception as e:
                        logger.error("Menu callback error: %s", e)
                return

        # Click outside items - close menu
        self.hide()

    def _check_focus(self):
        """Check if we should close due to focus loss."""
        try:
            if not self.focus_get():
                self.hide()
        except (tk.TclError, KeyError):
            pass

    def show(self, x: int, y: int):
        """
        Show dropdown at specified position with slide animation.

        Args:
            x: X position (screen coordinates)
            y: Y position (screen coordinates)
        """
        if self._visible or self._animating:
            return

        self._target_y = y
        self._current_height = 0

        # Position and show
        self.geometry(f"{self.width}x1+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_set()

        self._visible = True
        self._animate_show()

        logger.debug("Dropdown shown at (%d, %d)", x, y)

    def hide(self):
        """Hide dropdown with slide animation."""
        if not self._visible:
            return

        self._animate_hide()

    def _animate_show(self, step: int = 0, total_steps: int = 12):
        """Animate dropdown sliding down."""
        if step >= total_steps:
            self._animating = False
            self._current_height = self.total_height
            self._draw()
            return

        self._animating = True

        # Ease-out animation
        progress = step / total_steps
        eased = 1 - (1 - progress) ** 3  # Cubic ease-out

        self._current_height = int(self.total_height * eased)
        height = max(1, self._current_height)

        try:
            self.geometry(f"{self.width}x{height}")
            self.canvas.configure(height=height)
            self._draw()
            self.after(12, lambda: self._animate_show(step + 1, total_steps))
        except tk.TclError:
            self._animating = False

    def _animate_hide(self, step: int = 0, total_steps: int = 8):
        """Animate dropdown sliding up."""
        if step >= total_steps:
            self._animating = False
            self._visible = False
            self.withdraw()
            return

        self._animating = True

        # Ease-in animation
        progress = step / total_steps
        eased = progress ** 2  # Quadratic ease-in

        self._current_height = int(self.total_height * (1 - eased))
        height = max(1, self._current_height)

        try:
            self.geometry(f"{self.width}x{height}")
            self.canvas.configure(height=height)
            self._draw()
            self.after(10, lambda: self._animate_hide(step + 1, total_steps))
        except tk.TclError:
            self._animating = False
            self._visible = False
            try:
                self.withdraw()
            except tk.TclError:
                pass

    def toggle(self, x: int, y: int):
        """Toggle dropdown visibility."""
        if self._visible:
            self.hide()
        else:
            self.show(x, y)
