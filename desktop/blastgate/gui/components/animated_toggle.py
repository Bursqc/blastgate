"""
AnimatedToggle - Smooth animated toggle switch widget

A custom tkinter toggle switch with:
- Smooth color fade animation on state change
- Customizable ON/OFF colors
- Rounded pill-shaped design
- Click handler callback
"""
import logging
import tkinter as tk
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class AnimatedToggle(tk.Canvas):
    """
    Animated toggle switch with smooth fade transition.

    Features:
    - Pill-shaped toggle track
    - Circular sliding knob
    - Smooth color animation on toggle
    - Customizable colors for ON/OFF states

    Example:
        >>> toggle = AnimatedToggle(parent, on_toggle=lambda state: print(state))
        >>> toggle.set_state(True)  # Turn ON with animation
        >>> toggle.set_state(False, animate=False)  # Turn OFF instantly
    """

    def __init__(
        self,
        master: tk.Widget,
        width: int = 60,
        height: int = 30,
        on_color: str = "#2a9fd6",
        off_color: str = "#4a4a4a",
        knob_color: str = "#ffffff",
        on_toggle: Optional[Callable[[bool], None]] = None,
        initial_state: bool = False,
    ):
        """
        Initialize AnimatedToggle widget.

        Args:
            master: Parent widget
            width: Toggle width in pixels
            height: Toggle height in pixels
            on_color: Track color when ON (hex)
            off_color: Track color when OFF (hex)
            knob_color: Knob/circle color (hex)
            on_toggle: Callback when toggled, receives new state (bool)
            initial_state: Initial toggle state
        """
        super().__init__(
            master,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=master.cget("bg") if hasattr(master, "cget") else "#222222",
        )

        self.w = width
        self.h = height
        self.on_color = on_color
        self.off_color = off_color
        self.knob_color = knob_color
        self.on_toggle = on_toggle

        self._state = initial_state
        self._animating = False
        self._anim_progress = 1.0 if initial_state else 0.0  # 0=OFF, 1=ON

        # Calculate dimensions
        self._padding = 3
        self._knob_radius = (height - 2 * self._padding) // 2
        self._track_radius = height // 2

        # Draw initial state
        self._draw()

        # Bind click
        self.bind("<Button-1>", self._on_click)
        self.configure(cursor="hand2")

        logger.debug("AnimatedToggle created, initial state: %s", initial_state)

    def _lerp_color(self, c1: str, c2: str, t: float) -> str:
        """Interpolate between two hex colors."""
        def hex_to_rgb(h):
            h = h.lstrip("#")
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

        def rgb_to_hex(rgb):
            return "#{:02x}{:02x}{:02x}".format(*rgb)

        r1, g1, b1 = hex_to_rgb(c1)
        r2, g2, b2 = hex_to_rgb(c2)

        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)

        return rgb_to_hex((r, g, b))

    def _draw(self) -> None:
        """Draw the toggle in current state."""
        self.delete("all")

        # Current color based on animation progress
        track_color = self._lerp_color(self.off_color, self.on_color, self._anim_progress)

        # Draw track (pill shape)
        r = self._track_radius
        self.create_oval(0, 0, 2 * r, self.h, fill=track_color, outline="")
        self.create_oval(self.w - 2 * r, 0, self.w, self.h, fill=track_color, outline="")
        self.create_rectangle(r, 0, self.w - r, self.h, fill=track_color, outline="")

        # Calculate knob position based on animation progress
        knob_start_x = self._padding + self._knob_radius
        knob_end_x = self.w - self._padding - self._knob_radius
        knob_x = knob_start_x + (knob_end_x - knob_start_x) * self._anim_progress
        knob_y = self.h // 2

        # Draw knob (circle)
        kr = self._knob_radius
        self.create_oval(
            knob_x - kr,
            knob_y - kr,
            knob_x + kr,
            knob_y + kr,
            fill=self.knob_color,
            outline=""
        )

    def _on_click(self, event: tk.Event) -> None:
        """Handle click to toggle state."""
        if self._animating:
            return

        new_state = not self._state
        self.set_state(new_state, animate=True)

        if callable(self.on_toggle):
            try:
                self.on_toggle(new_state)
            except Exception as e:
                logger.error("Error in on_toggle callback: %s", e)

    def set_state(self, state: bool, animate: bool = True) -> None:
        """
        Set toggle state.

        Args:
            state: New state (True=ON, False=OFF)
            animate: Whether to animate the transition
        """
        if state == self._state and not animate:
            return

        self._state = state

        if animate:
            self._animate_to(1.0 if state else 0.0)
        else:
            self._anim_progress = 1.0 if state else 0.0
            self._draw()

    def get_state(self) -> bool:
        """Get current toggle state."""
        return self._state

    def _animate_to(self, target: float, duration_ms: int = 200, steps: int = 15) -> None:
        """Animate to target progress value."""
        if self._animating:
            return

        self._animating = True
        start = self._anim_progress
        delta = target - start
        step_delay = max(10, duration_ms // steps)
        step_delta = delta / steps

        def step(remaining: int) -> None:
            if remaining <= 0:
                self._anim_progress = target
                self._animating = False
                self._draw()
                return

            self._anim_progress += step_delta
            self._anim_progress = max(0.0, min(1.0, self._anim_progress))
            self._draw()

            try:
                self.after(step_delay, lambda: step(remaining - 1))
            except tk.TclError:
                self._animating = False

        step(steps)


class TriStateToggle(tk.Frame):
    """
    Three-state toggle for AUTO/ON/OFF selection.

    Displays three connected pill-shaped buttons with smooth
    color transitions when selection changes.

    Example:
        >>> toggle = TriStateToggle(parent, on_change=lambda s: print(s))
        >>> toggle.set_state("on")  # Select ON
    """

    def __init__(
        self,
        master: tk.Widget,
        width: int = 180,
        height: int = 36,
        auto_color: str = "#6c757d",
        on_color: str = "#2a9fd6",
        off_color: str = "#dc3545",
        inactive_color: str = "#3a3a3a",
        text_color: str = "#ffffff",
        on_change: Optional[Callable[[str], None]] = None,
        initial_state: str = "auto",
        labels: tuple = ("AUTO", "ON", "OFF"),
    ):
        """
        Initialize TriStateToggle widget.

        Args:
            master: Parent widget
            width: Total width in pixels
            height: Height in pixels
            auto_color: Color when AUTO is selected
            on_color: Color when ON is selected
            off_color: Color when OFF is selected
            inactive_color: Color for unselected options
            text_color: Text color
            on_change: Callback when state changes, receives state string
            initial_state: Initial state ("auto", "on", "off")
            labels: Tuple of labels for (auto, on, off)
        """
        super().__init__(master)

        self.width = width
        self.height = height
        self.auto_color = auto_color
        self.on_color = on_color
        self.off_color = off_color
        self.inactive_color = inactive_color
        self.text_color = text_color
        self.on_change = on_change
        self.labels = labels

        self._state = initial_state
        self._animating = False
        # Animation progress for each button: 0=inactive, 1=active
        self._progress = {"auto": 0.0, "on": 0.0, "off": 0.0}
        self._progress[initial_state] = 1.0

        self._btn_width = width // 3

        # Create canvas
        try:
            bg = master.cget("bg")
        except (tk.TclError, AttributeError):
            bg = "#222222"

        self.canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=bg,
        )
        self.canvas.pack()

        self._draw()

        # Bind clicks
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.configure(cursor="hand2")

        logger.debug("TriStateToggle created, initial state: %s", initial_state)

    def _get_active_color(self, state: str) -> str:
        """Get active color for a state."""
        return {"auto": self.auto_color, "on": self.on_color, "off": self.off_color}.get(state, self.auto_color)

    def _lerp_color(self, c1: str, c2: str, t: float) -> str:
        """Interpolate between two hex colors."""
        def hex_to_rgb(h):
            h = h.lstrip("#")
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

        def rgb_to_hex(rgb):
            return "#{:02x}{:02x}{:02x}".format(*rgb)

        r1, g1, b1 = hex_to_rgb(c1)
        r2, g2, b2 = hex_to_rgb(c2)

        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)

        return rgb_to_hex((r, g, b))

    def _draw(self) -> None:
        """Draw the toggle in current state."""
        self.canvas.delete("all")

        states = ["auto", "on", "off"]
        r = self.height // 2  # corner radius

        for i, state in enumerate(states):
            x1 = i * self._btn_width
            x2 = x1 + self._btn_width

            # Calculate color based on progress
            active_color = self._get_active_color(state)
            progress = self._progress[state]
            color = self._lerp_color(self.inactive_color, active_color, progress)

            # Draw button segment
            if i == 0:  # First - round left corners
                self.canvas.create_oval(x1, 0, x1 + 2 * r, self.height, fill=color, outline="")
                self.canvas.create_rectangle(x1 + r, 0, x2, self.height, fill=color, outline="")
            elif i == 2:  # Last - round right corners
                self.canvas.create_oval(x2 - 2 * r, 0, x2, self.height, fill=color, outline="")
                self.canvas.create_rectangle(x1, 0, x2 - r, self.height, fill=color, outline="")
            else:  # Middle - no rounded corners
                self.canvas.create_rectangle(x1, 0, x2, self.height, fill=color, outline="")

            # Draw separator lines (subtle)
            if i < 2:
                self.canvas.create_line(x2, 4, x2, self.height - 4, fill="#555555", width=1)

            # Draw text
            text_x = (x1 + x2) // 2
            text_y = self.height // 2
            self.canvas.create_text(
                text_x, text_y,
                text=self.labels[i],
                fill=self.text_color,
                font=("Segoe UI", 10, "bold" if progress > 0.5 else "normal")
            )

    def _on_click(self, event: tk.Event) -> None:
        """Handle click to change state."""
        if self._animating:
            return

        # Determine which button was clicked
        x = event.x
        states = ["auto", "on", "off"]
        clicked_idx = min(2, max(0, x // self._btn_width))
        new_state = states[clicked_idx]

        if new_state == self._state:
            return

        self.set_state(new_state, animate=True)

        if callable(self.on_change):
            try:
                self.on_change(new_state)
            except Exception as e:
                logger.error("Error in on_change callback: %s", e)

    def set_state(self, state: str, animate: bool = True) -> None:
        """
        Set toggle state.

        Args:
            state: New state ("auto", "on", "off")
            animate: Whether to animate the transition
        """
        if state not in ("auto", "on", "off"):
            logger.warning("Invalid state: %s", state)
            return

        old_state = self._state
        self._state = state

        if animate and old_state != state:
            self._animate_to(old_state, state)
        else:
            for s in ("auto", "on", "off"):
                self._progress[s] = 1.0 if s == state else 0.0
            self._draw()

    def get_state(self) -> str:
        """Get current toggle state."""
        return self._state

    def _animate_to(self, from_state: str, to_state: str, duration_ms: int = 200, steps: int = 15) -> None:
        """Animate transition between states."""
        if self._animating:
            return

        self._animating = True
        step_delay = max(10, duration_ms // steps)
        step_delta = 1.0 / steps

        def step(remaining: int) -> None:
            if remaining <= 0:
                self._progress[from_state] = 0.0
                self._progress[to_state] = 1.0
                self._animating = False
                self._draw()
                return

            # Fade out old, fade in new
            self._progress[from_state] = max(0.0, self._progress[from_state] - step_delta)
            self._progress[to_state] = min(1.0, self._progress[to_state] + step_delta)
            self._draw()

            try:
                self.canvas.after(step_delay, lambda: step(remaining - 1))
            except tk.TclError:
                self._animating = False

        step(steps)


class TwoStateToggle(tk.Frame):
    """
    Two-state toggle for AUTO/MANUAL selection with labels.

    Displays a sliding toggle with two labeled options and smooth
    color transitions when selection changes.

    Example:
        >>> toggle = TwoStateToggle(parent, on_change=lambda s: print(s))
        >>> toggle.set_state("right")  # Select MANUAL
    """

    def __init__(
        self,
        master: tk.Widget,
        width: int = 160,
        height: int = 36,
        left_color: str = "#2a9fd6",
        right_color: str = "#f0ad4e",
        inactive_color: str = "#3a3a3a",
        text_color: str = "#ffffff",
        on_change: Optional[Callable[[str], None]] = None,
        initial_state: str = "left",
        labels: tuple = ("AUTO", "MANUAL"),
    ):
        """
        Initialize TwoStateToggle widget.

        Args:
            master: Parent widget
            width: Total width in pixels
            height: Height in pixels
            left_color: Color when left option is selected
            right_color: Color when right option is selected
            inactive_color: Color for unselected option
            text_color: Text color
            on_change: Callback when state changes, receives "left" or "right"
            initial_state: Initial state ("left" or "right")
            labels: Tuple of labels for (left, right)
        """
        super().__init__(master)

        self.width = width
        self.height = height
        self.left_color = left_color
        self.right_color = right_color
        self.inactive_color = inactive_color
        self.text_color = text_color
        self.on_change = on_change
        self.labels = labels

        self._state = initial_state
        self._animating = False
        # Animation progress: 0=left, 1=right
        self._progress = 0.0 if initial_state == "left" else 1.0

        self._btn_width = width // 2

        # Create canvas
        try:
            bg = master.cget("bg")
        except (tk.TclError, AttributeError):
            bg = "#222222"

        self.canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=bg,
        )
        self.canvas.pack()

        self._draw()

        # Bind clicks
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.configure(cursor="hand2")

        logger.debug("TwoStateToggle created, initial state: %s", initial_state)

    def _lerp_color(self, c1: str, c2: str, t: float) -> str:
        """Interpolate between two hex colors."""
        def hex_to_rgb(h):
            h = h.lstrip("#")
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

        def rgb_to_hex(rgb):
            return "#{:02x}{:02x}{:02x}".format(*rgb)

        r1, g1, b1 = hex_to_rgb(c1)
        r2, g2, b2 = hex_to_rgb(c2)

        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)

        return rgb_to_hex((r, g, b))

    def _draw(self) -> None:
        """Draw the toggle in current state."""
        self.canvas.delete("all")

        r = self.height // 2  # corner radius

        # Left button
        left_active = 1.0 - self._progress
        left_color = self._lerp_color(self.inactive_color, self.left_color, left_active)

        # Draw left segment (rounded left corners)
        self.canvas.create_oval(0, 0, 2 * r, self.height, fill=left_color, outline="")
        self.canvas.create_rectangle(r, 0, self._btn_width, self.height, fill=left_color, outline="")

        # Right button
        right_active = self._progress
        right_color = self._lerp_color(self.inactive_color, self.right_color, right_active)

        # Draw right segment (rounded right corners)
        self.canvas.create_oval(self.width - 2 * r, 0, self.width, self.height, fill=right_color, outline="")
        self.canvas.create_rectangle(self._btn_width, 0, self.width - r, self.height, fill=right_color, outline="")

        # Draw separator line (subtle)
        self.canvas.create_line(self._btn_width, 4, self._btn_width, self.height - 4, fill="#555555", width=1)

        # Draw text labels
        for i, label in enumerate(self.labels):
            x1 = i * self._btn_width
            x2 = x1 + self._btn_width
            text_x = (x1 + x2) // 2
            text_y = self.height // 2

            is_active = (i == 0 and left_active > 0.5) or (i == 1 and right_active > 0.5)
            self.canvas.create_text(
                text_x, text_y,
                text=label,
                fill=self.text_color,
                font=("Segoe UI", 10, "bold" if is_active else "normal")
            )

    def _on_click(self, event: tk.Event) -> None:
        """Handle click to change state."""
        if self._animating:
            return

        # Determine which side was clicked
        x = event.x
        new_state = "left" if x < self._btn_width else "right"

        if new_state == self._state:
            return

        self.set_state(new_state, animate=True)

        if callable(self.on_change):
            try:
                self.on_change(new_state)
            except Exception as e:
                logger.error("Error in on_change callback: %s", e)

    def set_state(self, state: str, animate: bool = True) -> None:
        """
        Set toggle state.

        Args:
            state: New state ("left" or "right")
            animate: Whether to animate the transition
        """
        if state not in ("left", "right"):
            logger.warning("Invalid state: %s", state)
            return

        self._state = state
        target = 0.0 if state == "left" else 1.0

        if animate:
            self._animate_to(target)
        else:
            self._progress = target
            self._draw()

    def get_state(self) -> str:
        """Get current toggle state."""
        return self._state

    def _animate_to(self, target: float, duration_ms: int = 200, steps: int = 15) -> None:
        """Animate to target progress value."""
        if self._animating:
            return

        self._animating = True
        start = self._progress
        delta = target - start
        step_delay = max(10, duration_ms // steps)
        step_delta = delta / steps

        def step(remaining: int) -> None:
            if remaining <= 0:
                self._progress = target
                self._animating = False
                self._draw()
                return

            self._progress += step_delta
            self._progress = max(0.0, min(1.0, self._progress))
            self._draw()

            try:
                self.canvas.after(step_delay, lambda: step(remaining - 1))
            except tk.TclError:
                self._animating = False

        step(steps)
