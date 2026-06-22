"""
RoundedTile - Animated node tile widget

A custom tkinter widget displaying node information with:
- Gradient rounded rectangle background
- Title, subtitle, metadata text
- Interactive "Open" button
- Context menu (rename, open)
- Smooth fade-in animation
- Cursor changes on hover
"""
import logging
import tkinter as tk
import ttkbootstrap as ttk
from typing import Optional, Callable

from ..utils import draw_rounded_rect, lerp_color

logger = logging.getLogger(__name__)


class RoundedTile(ttk.Frame):
    """
    Animated tile widget for displaying node information.

    Features:
    - Rounded rectangle with gradient background
    - Title (clickable for rename), subtitle, metadata
    - "Open" button (top-right)
    - Right-click context menu
    - Smooth fade-in animation
    - Interactive cursor changes

    Example:
        >>> tile = RoundedTile(parent, node_id="BG-123ABC",
        ...                    on_open=open_detail,
        ...                    on_rename=rename_node)
        >>> tile.set_text("Front Gate", "BG-123ABC", "OFFLINE")
        >>> tile.fade_in(ms_total=220)
    """

    def __init__(
        self,
        master: tk.Widget,
        node_id: str,
        on_open: Optional[Callable] = None,
        on_rename: Optional[Callable] = None,
        width: int = 420,
        height: int = 150,
        radius: int = 26,
        bg_from: str = "#101215",
        bg_to: str = "#1c1f24",
        text: str = "#f0f0f0",
        sub: str = "#9aa0a6",
    ):
        """
        Initialize RoundedTile widget.

        Args:
            master: Parent widget
            node_id: Node identifier (e.g., "BG-123ABC")
            on_open: Callback when tile is opened (double-click, "Open" button)
            on_rename: Callback when rename is requested (title click, context menu)
            width: Tile width in pixels
            height: Tile height in pixels
            radius: Corner radius for rounded rectangle
            bg_from: Start color for gradient (hex)
            bg_to: End color for gradient (hex)
            text: Main text color (hex)
            sub: Subtitle/metadata text color (hex)
        """
        super().__init__(master)

        self.node_id = node_id
        self.on_open = on_open
        self.on_rename = on_rename

        self.w = width
        self.h = height
        self.r = radius

        self.bg_from = bg_from
        self.bg_to = bg_to
        self.text = text
        self.sub = sub

        # Create canvas
        try:
            parent_bg = master.winfo_toplevel().cget("bg")
        except (tk.TclError, AttributeError) as e:
            logger.debug("Failed to get parent bg color, using default: %s", e)
            parent_bg = "#222222"

        self.canvas = tk.Canvas(
            self,
            width=self.w,
            height=self.h,
            highlightthickness=0,
            bd=0,
            bg=parent_bg,
        )
        self.canvas.pack(fill="both", expand=False)

        # Draw rounded background
        self._rect_id = draw_rounded_rect(
            self.canvas,
            2,
            2,
            self.w - 2,
            self.h - 2,
            radius=self.r,
            fill=self.bg_from,
            outline="#2a2f35",
            width=1,
        )

        # Text elements
        self._title_id = self.canvas.create_text(
            22,
            28,
            anchor="w",
            text="(unassigned)",
            fill=self.text,
            font=("Segoe UI", 14, "bold"),
        )

        self._sub_id = self.canvas.create_text(
            22,
            58,
            anchor="w",
            text=self.node_id,
            fill=self.sub,
            font=("Segoe UI", 10),
        )

        self._meta_id = self.canvas.create_text(
            22, 92, anchor="w", text="", fill=self.sub, font=("Segoe UI", 11)
        )

        self._open_id = self.canvas.create_text(
            self.w - 22,
            28,
            anchor="e",
            text="Open",
            fill="#4aa3ff",
            font=("Segoe UI", 11, "bold"),
        )

        # Context menu
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Rename…", command=self._rename_prompt)
        self.menu.add_command(label="Open", command=self._open)

        # Bind events
        self._bind_events()

        # Animation state
        self._animating = False
        self._t = 0.0
        self._base_from = self.bg_from
        self._base_to = self.bg_to

        logger.debug("RoundedTile created for node %s", node_id)

    def _bind_events(self) -> None:
        """Bind mouse events for interactivity."""
        # Double-click to open
        for tag in (self._rect_id, self._sub_id, self._meta_id, self._open_id):
            self.canvas.tag_bind(tag, "<Double-Button-1>", lambda _e: self._open())

        # Single-click on title for rename
        self.canvas.tag_bind(self._title_id, "<Button-1>", lambda _e: self._rename_prompt())
        self.canvas.tag_bind(self._title_id, "<Double-Button-1>", lambda _e: self._open())

        # Single-click on "Open" button
        self.canvas.tag_bind(self._open_id, "<Button-1>", lambda _e: self._open())

        # Right-click context menu
        self.canvas.bind("<Button-3>", self._context_menu)

        # Hover cursor changes
        self.canvas.bind("<Motion>", self._motion)

    def _open(self) -> None:
        """Call on_open callback if provided."""
        if callable(self.on_open):
            try:
                self.on_open()
            except Exception as e:
                logger.error("Error in on_open callback for %s: %s", self.node_id, e)

    def _rename_prompt(self) -> None:
        """Call on_rename callback if provided."""
        if callable(self.on_rename):
            try:
                self.on_rename()
            except Exception as e:
                logger.error("Error in on_rename callback for %s: %s", self.node_id, e)

    def _context_menu(self, e: tk.Event) -> None:
        """Show context menu on right-click."""
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        except (tk.TclError, AttributeError) as err:
            logger.debug("Failed to show context menu: %s", err)
        finally:
            try:
                self.menu.grab_release()
            except (tk.TclError, AttributeError) as err:
                logger.debug("Failed to release menu grab: %s", err)

    def _motion(self, e: tk.Event) -> None:
        """Update cursor based on hover position."""
        try:
            x, y = e.x, e.y

            # Check if hovering over "Open" button
            bbox_open = self.canvas.bbox(self._open_id)
            if bbox_open and (bbox_open[0] <= x <= bbox_open[2]) and (bbox_open[1] <= y <= bbox_open[3]):
                self.canvas.configure(cursor="hand2")
                return

            # Check if hovering over title
            bbox_title = self.canvas.bbox(self._title_id)
            if bbox_title and (bbox_title[0] <= x <= bbox_title[2]) and (bbox_title[1] <= y <= bbox_title[3]):
                self.canvas.configure(cursor="xterm")
                return

            # Default cursor
            self.canvas.configure(cursor="")

        except (tk.TclError, AttributeError) as err:
            logger.debug("Error updating cursor: %s", err)
            try:
                self.canvas.configure(cursor="")
            except (tk.TclError, AttributeError):
                pass

    def set_text(self, title: str, subtitle: str, meta: str) -> None:
        """
        Update tile text content.

        Args:
            title: Main title (top)
            subtitle: Subtitle (middle)
            meta: Metadata text (bottom)
        """
        try:
            self.canvas.itemconfig(self._title_id, text=title)
            self.canvas.itemconfig(self._sub_id, text=subtitle)
            self.canvas.itemconfig(self._meta_id, text=meta)
            logger.debug("Updated tile text for %s: %s", self.node_id, title)
        except (tk.TclError, AttributeError) as e:
            logger.warning("Failed to update tile text for %s: %s", self.node_id, e)

    def set_tile_style(
        self, bg_from: str, bg_to: str, outline: str = "#2a2f35"
    ) -> None:
        """
        Update tile background colors.

        Args:
            bg_from: Start color for gradient (hex)
            bg_to: End color for gradient (hex)
            outline: Border color (hex)
        """
        self._base_from = bg_from
        self._base_to = bg_to

        try:
            self.canvas.itemconfig(self._rect_id, fill=bg_to, outline=outline)
            logger.debug("Updated tile style for %s", self.node_id)
        except (tk.TclError, AttributeError) as e:
            logger.warning("Failed to update tile style for %s: %s", self.node_id, e)

    def fade_in(self, ms_total: int = 220, steps: int = 10) -> None:
        """
        Animate smooth fade-in from bg_from to bg_to.

        Args:
            ms_total: Total animation duration in milliseconds
            steps: Number of animation steps (higher = smoother)

        Example:
            >>> tile.fade_in(ms_total=300, steps=15)
        """
        if self._animating:
            logger.debug("Already animating tile %s, skipping fade_in", self.node_id)
            return

        self._animating = True
        self._t = 0.0

        dt = 1.0 / max(1, steps)
        delay = max(10, ms_total // max(1, steps))

        c1 = self._base_from
        c2 = self._base_to

        def step() -> None:
            """Single animation step."""
            if not self._animating:
                return

            self._t += dt
            t = min(1.0, self._t)

            try:
                col = lerp_color(c1, c2, t)
                self.canvas.itemconfig(self._rect_id, fill=col)
            except (tk.TclError, AttributeError) as e:
                logger.debug("Animation step failed for %s: %s", self.node_id, e)
                self._animating = False
                return

            if t >= 1.0:
                self._animating = False
                logger.debug("Fade-in animation complete for %s", self.node_id)
                return

            try:
                self.after(delay, step)
            except (tk.TclError, AttributeError) as e:
                logger.debug("Failed to schedule animation step: %s", e)
                self._animating = False

        step()
