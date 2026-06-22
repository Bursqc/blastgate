"""
Blastgate application entry point

Run with: python -m blastgate

Architecture:
- Fully modular codebase (100% complete)
- Config: Pydantic models with validation
- Network: Clean UDP layer with proper error handling
- Controllers: AUTO mode business logic
- Utils: Type-safe helpers and validators
- GUI: Refactored components (dialogs, app, utils)
"""
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from blastgate.logging_config import setup_logging
from blastgate.constants import LOG_PATH, APP_VERSION

# Setup logging
logger = setup_logging("INFO", LOG_PATH, console=True)

logger.info("=" * 60)
logger.info("Blastgate v%s - Dust Collection Control System", APP_VERSION)
logger.info("=" * 60)
logger.info("Architecture: Fully Modular (100%% refactored)")
logger.info("Using:")
logger.info("  - Pydantic models for config validation")
logger.info("  - Refactored network layer (UDP)")
logger.info("  - AutoController for AUTO mode")
logger.info("  - Type-safe utilities")
logger.info("  - Comprehensive error handling")
logger.info("  - Modular GUI (dialogs, components, app)")
logger.info("=" * 60)

# Import and run application
logger.info("Starting Blastgate application...")

try:
    from blastgate.gui import App

    logger.info("Launching GUI (refactored)...")

    app = App()
    logger.info("Application window created successfully")

    # Start tkinter main loop
    app.mainloop()

    logger.info("Application closed normally")

except KeyboardInterrupt:
    logger.info("Application interrupted by user (Ctrl+C)")
    sys.exit(0)

except Exception as e:
    logger.error("Failed to start application: %s", e, exc_info=True)
    logger.error("Please check logs at: %s", LOG_PATH)
    sys.exit(1)
