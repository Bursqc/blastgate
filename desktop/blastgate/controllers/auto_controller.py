"""
AUTO mode controller for Blastgate

Implements automatic dust collection control logic:
- Threshold-based sensor monitoring with hysteresis
- Automatic relay on/off based on active sensors
- Automatic gate opening when above threshold
- Delayed gate closing after sensor goes below threshold
- Lockout mode support

State Machine:
1. Monitor all online nodes for threshold crossing
2. Turn relay ON if any sensor above threshold
3. Open gates for active sensors immediately
4. Keep gates open while sensor is active
5. Close gates after hold_ms delay when sensor goes below threshold
6. Turn relay OFF when all sensors below threshold

Example:
    >>> controller = AutoController(config, net_engine)
    >>> controller.process(nodes_online, app_mode="AUTO", lockout=False)
"""
import logging
from typing import Dict, List, Any, Optional
from ..utils import safe_node_id, now_ms
from ..network import NetEngine
from ..models.config import AppConfig

logger = logging.getLogger(__name__)


class AutoController:
    """
    Automatic dust collection controller.

    Manages relay and gate control based on sensor thresholds with hysteresis.

    Example:
        >>> config = load_config()
        >>> controller = AutoController(config, net_engine)
        >>> controller.process(status.nodes, app_mode="AUTO", lockout=False)
    """

    def __init__(self, config: AppConfig, net: NetEngine):
        """
        Initialize AUTO controller.

        Args:
            config: Application configuration (thresholds, hold times)
            net: Network engine for sending commands
        """
        self.cfg = config
        self.net = net

        # Threshold latch state: {node_id: bool}
        self._above_latched: Dict[str, bool] = {}

        # Relay state
        self._auto_relay_on: bool = False

        # Gate state: {node_id: bool}
        self._auto_gate_open: Dict[str, bool] = {}

        # Gate close deadlines: {node_id: timestamp_ms}
        self._auto_close_deadline_ms: Dict[str, int] = {}

        logger.info("AutoController initialized")

    def _get_thresholds(self, node_id: str) -> tuple[float, float, int]:
        """
        Get threshold, hysteresis, and hold time for node.

        Args:
            node_id: Node identifier

        Returns:
            Tuple of (threshold, hysteresis, hold_ms)
            Uses global defaults if node config not found
        """
        node_cfg = self.cfg.nodes.get(node_id)

        if node_cfg:
            threshold = node_cfg.get("threshold", 40.0)
            hyst = node_cfg.get("hyst", 2.0)
            hold_ms = node_cfg.get("hold_ms", 5000)
        else:
            # Global defaults
            threshold = 40.0
            hyst = 2.0
            hold_ms = 5000

        return (float(threshold), float(hyst), int(hold_ms))

    def process(
        self,
        nodes_online: List[Dict[str, Any]],
        app_mode: str,
        lockout: bool,
    ) -> None:
        """
        Process AUTO control logic for current node states.

        Args:
            nodes_online: List of online node dicts from hub status
            app_mode: Current application mode ("AUTO", "MANUAL", "LOCKED")
            lockout: Whether lockout mode is active

        Returns:
            None (sends commands via net engine)

        Example:
            >>> controller.process(status.nodes, app_mode="AUTO", lockout=False)
        """
        # Skip if not in AUTO mode or lockout active
        if lockout or app_mode != "AUTO":
            return

        # Step 1: Update threshold latch state for all nodes
        above_map: Dict[str, bool] = {}

        for node in nodes_online:
            node_id = safe_node_id(node)
            if not node_id:
                continue

            threshold, hyst, _hold = self._get_thresholds(node_id)
            value_raw = node.get("value", None)

            # Previous latch state
            prev_above = bool(self._above_latched.get(node_id, False))
            cur_above = prev_above

            # Parse sensor value
            try:
                value = float(value_raw) if value_raw is not None else None
            except (ValueError, TypeError) as e:
                logger.debug("Invalid sensor value for %s: %s (%s)", node_id, value_raw, e)
                value = None

            if value is None:
                # No valid reading: treat as below threshold
                cur_above = False
            else:
                # Hysteresis logic
                on_threshold = threshold + hyst
                off_threshold = threshold - hyst

                if prev_above:
                    # Currently latched ON: check if value drops below off threshold
                    if value < off_threshold:
                        cur_above = False
                        logger.info("Node %s crossed below threshold (%.2f < %.2f)",
                                   node_id, value, off_threshold)
                else:
                    # Currently latched OFF: check if value rises above on threshold
                    if value > on_threshold:
                        cur_above = True
                        logger.info("Node %s crossed above threshold (%.2f > %.2f)",
                                   node_id, value, on_threshold)

            self._above_latched[node_id] = cur_above
            above_map[node_id] = cur_above

        # Step 2: Relay control - ON if any sensor above threshold
        any_above = any(above_map.values()) if above_map else False

        if any_above and (not self._auto_relay_on):
            self._auto_relay_on = True
            self.net.send("relay", "on")
            logger.info("AUTO: Relay turned ON (sensors active)")

        elif (not any_above) and self._auto_relay_on:
            self._auto_relay_on = False
            self.net.send("relay", "off")
            logger.info("AUTO: Relay turned OFF (no sensors active)")

        # Step 3: Gate control - Open immediately if above, close after hold_ms delay
        now = now_ms()

        for node in nodes_online:
            node_id = safe_node_id(node)
            if not node_id:
                continue

            _threshold, _hyst, hold_ms = self._get_thresholds(node_id)

            if above_map.get(node_id, False):
                # Sensor above threshold: open gate immediately, cancel close deadline
                self._auto_close_deadline_ms.pop(node_id, None)

                if not self._auto_gate_open.get(node_id, False):
                    self._auto_gate_open[node_id] = True
                    self.net.send("gate", node_id, "open")
                    logger.info("AUTO: Gate opened for %s", node_id)

            else:
                # Sensor below threshold: schedule gate close after hold_ms
                if self._auto_gate_open.get(node_id, False):
                    if node_id not in self._auto_close_deadline_ms:
                        deadline = now + hold_ms
                        self._auto_close_deadline_ms[node_id] = deadline
                        logger.debug("AUTO: Gate close scheduled for %s (hold=%dms)",
                                    node_id, hold_ms)

        # Step 4: Check deadlines and close gates
        for node_id, deadline in list(self._auto_close_deadline_ms.items()):
            if now >= int(deadline):
                self._auto_gate_open[node_id] = False
                self.net.send("gate", node_id, "close")
                self._auto_close_deadline_ms.pop(node_id, None)
                logger.info("AUTO: Gate closed for %s (hold timeout reached)", node_id)

    def reset(self) -> None:
        """
        Reset AUTO controller state.

        Clears all latches, deadlines, and state tracking.
        Does not send any commands.

        Example:
            >>> controller.reset()  # Switch to MANUAL mode
        """
        self._above_latched.clear()
        self._auto_relay_on = False
        self._auto_gate_open.clear()
        self._auto_close_deadline_ms.clear()
        logger.info("AutoController state reset")
