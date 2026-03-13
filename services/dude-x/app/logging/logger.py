"""Configure logging from settings."""
import logging

from app.core.config import settings


def configure_logging() -> None:
    """Call at startup."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
