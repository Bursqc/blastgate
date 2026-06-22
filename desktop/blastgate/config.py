"""
Configuration loading and saving with Pydantic validation
"""
import json
import logging
from pathlib import Path
from typing import Optional
from pydantic import ValidationError

from .models.config import AppConfig
from .constants import CFG_PATH
from .exceptions import ConfigurationError

logger = logging.getLogger(__name__)


def load_config(path: Optional[Path] = None) -> AppConfig:
    """
    Load configuration from JSON file with automatic migration and validation.

    Args:
        path: Path to config file (defaults to CFG_PATH constant)

    Returns:
        AppConfig instance with validated configuration

    Raises:
        ConfigurationError: If config file cannot be read (after fallback to defaults)

    Example:
        >>> config = load_config()
        >>> print(config.hub_lan_ip)
        '192.168.1.116'
    """
    if path is None:
        path = CFG_PATH

    # If config doesn't exist, create default
    if not path.exists():
        logger.info("Config file not found at %s, creating default", path)
        cfg = AppConfig()
        save_config(cfg, path)
        return cfg

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        logger.debug("Loaded config from %s", path)

        # Validate and parse with Pydantic
        config = AppConfig.model_validate(data)

        # Optional: Auto-migration for old configs
        # if "version" not in data:
        #     logger.info("Migrating config to new format")
        #     config = migrate_v1_to_v2(config)
        #     save_config(config, path)

        return config

    except json.JSONDecodeError as e:
        logger.error("Config file has invalid JSON: %s", e)
        logger.warning("Using default configuration")
        cfg = AppConfig()
        # Try to backup broken config
        try:
            backup_path = path.with_suffix('.json.bak')
            path.rename(backup_path)
            logger.info("Backed up broken config to %s", backup_path)
        except (OSError, PermissionError) as backup_error:
            logger.warning("Could not backup broken config: %s", backup_error)

        save_config(cfg, path)
        return cfg

    except ValidationError as e:
        logger.error("Config validation failed: %s", e)
        logger.warning("Using default configuration, invalid fields will be reset")
        # Try to preserve valid fields
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Create config with defaults, then try to update with valid fields
            cfg = AppConfig()
            for field in cfg.model_fields:
                if field in data:
                    try:
                        setattr(cfg, field, data[field])
                    except (ValidationError, ValueError) as field_error:
                        logger.warning("Skipping invalid field %s: %s", field, field_error)
            save_config(cfg, path)
            return cfg
        except Exception:
            # If all else fails, return defaults
            cfg = AppConfig()
            save_config(cfg, path)
            return cfg

    except (OSError, PermissionError) as e:
        logger.error("Cannot read config file: %s", e)
        raise ConfigurationError(f"Cannot read config from {path}: {e}")


def save_config(cfg: AppConfig, path: Optional[Path] = None) -> None:
    """
    Save configuration to JSON file preserving format.

    Args:
        cfg: AppConfig instance to save
        path: Path to config file (defaults to CFG_PATH constant)

    Raises:
        ConfigurationError: If config cannot be saved

    Example:
        >>> config = AppConfig(hub_lan_ip="192.168.1.50")
        >>> save_config(config)
    """
    if path is None:
        path = CFG_PATH

    try:
        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize to dict, then to JSON
        data = cfg.model_dump(mode='json', exclude_none=False)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.debug("Saved config to %s", path)

    except (OSError, PermissionError, TypeError) as e:
        logger.error("Failed to save config: %s", e)
        raise ConfigurationError(f"Cannot save config to {path}: {e}")


def migrate_v1_to_v2(config: AppConfig) -> AppConfig:
    """
    Migrate config from v1.x format to v2.0 format (if needed in future).

    Args:
        config: AppConfig instance

    Returns:
        Migrated AppConfig instance
    """
    # Placeholder for future migrations
    logger.info("Config migration: v1 -> v2 (no changes needed)")
    return config
