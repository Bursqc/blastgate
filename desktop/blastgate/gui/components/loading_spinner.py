"""
Loading spinner and progress indicators for Blastgate GUI
"""
import logging
import math
import tkinter as tk
from typing import Optional

logger = logging.getLogger(__name__)


def _get_parent_bg(parent) -> str:
    """Get background color from parent widget for theme compatibility"""
    try:
        style = parent.winfo_toplevel().style
        bg = style.lookup("TFrame", "background")
        if bg:
            return bg
    except (AttributeError, Exception):
        pass

    try:
        return str(parent.cget("background"))
    except (tk.TclError, AttributeError):
        pass

    return ""


class LoadingSpinner(tk.Canvas):
    """
    Animated loading spinner widget.

    Shows a rotating circular progress indicator during async operations.
    """

    def __init__(self, parent, size: int = 32, color: str = "#3498db", width: int = 3, **kwargs):
        """
        Initialize loading spinner.

        Args:
            parent: Parent widget
            size: Spinner diameter in pixels
            color: Spinner color (hex)
            width: Line width
            **kwargs: Additional canvas options
        """
        # Match parent background for theme compatibility
        bg = _get_parent_bg(parent)
        if bg and "bg" not in kwargs and "background" not in kwargs:
            kwargs["bg"] = bg

        super().__init__(parent, width=size, height=size, highlightthickness=0, **kwargs)

        self.size = size
        self.color = color
        self.line_width = width
        self._angle = 0
        self._running = False
        self._after_id: Optional[str] = None

        # Create arc
        pad = width + 2
        self._arc = self.create_arc(
            pad, pad, size - pad, size - pad,
            start=0, extent=270,
            outline=color, width=width,
            style=tk.ARC
        )

        logger.debug("LoadingSpinner created (size=%d, color=%s)", size, color)

    def start(self) -> None:
        """Start spinner animation"""
        if not self._running:
            self._running = True
            self._animate()
            logger.debug("Spinner started")

    def stop(self) -> None:
        """Stop spinner animation"""
        if self._running:
            self._running = False
            if self._after_id:
                self.after_cancel(self._after_id)
                self._after_id = None
            logger.debug("Spinner stopped")

    def _animate(self) -> None:
        """Animation loop"""
        if not self._running:
            return

        # Rotate arc
        self._angle = (self._angle + 15) % 360

        try:
            self.itemconfig(self._arc, start=self._angle)
        except tk.TclError as e:
            logger.debug("Spinner animation error: %s", e)
            self._running = False
            return

        # Schedule next frame (60 FPS)
        self._after_id = self.after(16, self._animate)

    def destroy(self) -> None:
        """Clean up spinner"""
        self.stop()
        super().destroy()


class StatusIndicator(tk.Canvas):
    """
    Status indicator with colored dot and animation patterns.

    Patterns per state:
    - offline:   slow red blink    (250ms on / 1750ms off)
    - searching: fast orange blink (180ms on / 180ms off)
    - online:    slow green breathe
    - active:    fast blue breathe
    - warning:   medium orange blink
    - unknown:   static gray
    """

    PATTERNS = {
        "online":    {"color": "#2ecc71", "mode": "breathe", "min_a": 0.50, "max_a": 1.0, "step": 0.025},
        "offline":   {"color": "#e74c3c", "mode": "blink",   "on_ms": 250,  "off_ms": 1750},
        "searching": {"color": "#f39c12", "mode": "blink",   "on_ms": 180,  "off_ms": 180},
        "active":    {"color": "#3498db", "mode": "breathe", "min_a": 0.20, "max_a": 1.0, "step": 0.06},
        "warning":   {"color": "#f39c12", "mode": "blink",   "on_ms": 450,  "off_ms": 450},
        "unknown":   {"color": "#95a5a6", "mode": "static"},
    }

    def __init__(self, parent, status: str = "unknown", size: int = 12, **kwargs):
        bg = _get_parent_bg(parent)
        if bg and "bg" not in kwargs and "background" not in kwargs:
            kwargs["bg"] = bg

        super().__init__(parent, width=size, height=size, highlightthickness=0, **kwargs)

        self.size = size
        self._status = status
        self._anim_id: Optional[str] = None

        # breathe state
        self._alpha = 1.0
        self._alpha_dir = -1

        # blink state
        self._blink_phase = "on"

        pad = 2
        p = self.PATTERNS.get(status, self.PATTERNS["unknown"])
        self._dot = self.create_oval(
            pad, pad, size - pad, size - pad,
            fill=p["color"], outline=""
        )

        self._start_anim()
        logger.debug("StatusIndicator created (status=%s, size=%d)", status, size)

    def set_status(self, status: str) -> None:
        """Update status and restart animation."""
        if self._status == status:
            return

        old = self._status
        self._status = status
        self._stop_anim()

        p = self.PATTERNS.get(status, self.PATTERNS["unknown"])
        try:
            self.itemconfig(self._dot, fill=p["color"])
        except tk.TclError:
            return

        # Reset animation state
        self._alpha = 1.0
        self._alpha_dir = -1
        self._blink_phase = "on"

        self._start_anim()
        logger.debug("Status: %s -> %s", old, status)

    # ---- animation control ----

    def _start_anim(self) -> None:
        p = self.PATTERNS.get(self._status, self.PATTERNS["unknown"])
        mode = p.get("mode", "static")
        if mode == "breathe":
            self._anim_id = self.after(33, self._breathe)
        elif mode == "blink":
            self._blink_phase = "on"
            self._anim_id = self.after(0, self._blink)

    def _stop_anim(self) -> None:
        if self._anim_id:
            self.after_cancel(self._anim_id)
            self._anim_id = None

    # ---- breathe (smooth fade in/out) ----

    def _breathe(self) -> None:
        p = self.PATTERNS.get(self._status, self.PATTERNS["unknown"])
        if p.get("mode") != "breathe":
            return

        min_a = p.get("min_a", 0.3)
        max_a = p.get("max_a", 1.0)
        step  = p.get("step",  0.04)

        self._alpha += step * self._alpha_dir
        if self._alpha >= max_a:
            self._alpha = max_a
            self._alpha_dir = -1
        elif self._alpha <= min_a:
            self._alpha = min_a
            self._alpha_dir = 1

        try:
            self.itemconfig(self._dot, fill=self._blend(p["color"], self._alpha))
        except tk.TclError:
            return

        self._anim_id = self.after(33, self._breathe)

    # ---- blink (on/off) ----

    def _blink(self) -> None:
        p = self.PATTERNS.get(self._status, self.PATTERNS["unknown"])
        if p.get("mode") != "blink":
            return

        try:
            canvas_bg = self.cget("background") or "#111111"
            if self._blink_phase == "on":
                self.itemconfig(self._dot, fill=p["color"])
                self._blink_phase = "off"
                self._anim_id = self.after(p["on_ms"], self._blink)
            else:
                self.itemconfig(self._dot, fill=canvas_bg)
                self._blink_phase = "on"
                self._anim_id = self.after(p["off_ms"], self._blink)
        except tk.TclError:
            return

    # ---- helper ----

    @staticmethod
    def _blend(hex_color: str, alpha: float) -> str:
        """Blend hex_color toward near-black by alpha (0=dark, 1=full color)."""
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = int(r * alpha + 18 * (1 - alpha))
        g = int(g * alpha + 18 * (1 - alpha))
        b = int(b * alpha + 18 * (1 - alpha))
        return f"#{r:02x}{g:02x}{b:02x}"

    def destroy(self) -> None:
        self._stop_anim()
        super().destroy()


class ProgressBar(tk.Canvas):
    """
    Animated progress bar with smooth transitions.
    """

    def __init__(self, parent, width: int = 200, height: int = 6,
                 color: str = "#3498db", bg_color: str = "#ecf0f1", **kwargs):
        """
        Initialize progress bar.

        Args:
            parent: Parent widget
            width: Bar width in pixels
            height: Bar height in pixels
            color: Progress color (hex)
            bg_color: Background color (hex)
            **kwargs: Additional canvas options
        """
        # Match parent background for theme compatibility
        bg = _get_parent_bg(parent)
        if bg and "bg" not in kwargs and "background" not in kwargs:
            kwargs["bg"] = bg

        super().__init__(parent, width=width, height=height, highlightthickness=0, **kwargs)

        self.bar_width = width
        self.bar_height = height
        self.color = color
        self._bg_color = bg_color

        # Background
        self._bg_rect = self.create_rectangle(0, 0, width, height, fill=bg_color, outline="")

        # Progress rectangle
        self._progress_rect = self.create_rectangle(
            0, 0, 0, height,
            fill=color, outline=""
        )

        self._current_progress = 0.0
        self._target_progress = 0.0
        self._animating = False
        self._anim_id: Optional[str] = None

        # Handle resize (when packed with fill="x")
        self.bind("<Configure>", self._on_resize)

        logger.debug("ProgressBar created (width=%d, height=%d)", width, height)

    def _on_resize(self, event) -> None:
        """Handle canvas resize to update bar dimensions"""
        new_width = event.width
        if new_width > 0 and new_width != self.bar_width:
            self.bar_width = new_width
            try:
                self.coords(self._bg_rect, 0, 0, new_width, self.bar_height)
                self._update_bar()
            except tk.TclError:
                pass

    def set_progress(self, progress: float, animate: bool = True) -> None:
        """
        Set progress value.

        Args:
            progress: Progress value (0.0 to 1.0)
            animate: Whether to animate transition
        """
        progress = max(0.0, min(1.0, progress))
        self._target_progress = progress

        if animate and not self._animating:
            self._animating = True
            self._animate_progress()
        elif not animate:
            self._current_progress = progress
            self._update_bar()

    def _animate_progress(self) -> None:
        """Animate progress bar to target"""
        if not self._animating:
            return

        # Smooth interpolation
        diff = self._target_progress - self._current_progress

        if abs(diff) < 0.01:
            self._current_progress = self._target_progress
            self._update_bar()
            self._animating = False
            return

        self._current_progress += diff * 0.2
        self._update_bar()

        # Schedule next frame
        self._anim_id = self.after(16, self._animate_progress)

    def _update_bar(self) -> None:
        """Update progress bar visual"""
        width = int(self.bar_width * self._current_progress)
        try:
            self.coords(self._progress_rect, 0, 0, width, self.bar_height)
        except tk.TclError as e:
            logger.debug("Progress bar update error: %s", e)

    def reset(self) -> None:
        """Reset progress to 0"""
        self.set_progress(0.0, animate=False)

    def destroy(self) -> None:
        """Clean up progress bar"""
        self._animating = False
        if self._anim_id:
            self.after_cancel(self._anim_id)
        super().destroy()
