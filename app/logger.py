import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Create logs directory if it doesn't exist
logs_dir = Path("/app/logs")
logs_dir.mkdir(exist_ok=True)


def setup_logger(name):
    """
    Setup logger that writes to console and file
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Clear existing handlers to avoid duplicates
    if logger.handlers:
        logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Create file handler that writes to a file (rotating to keep size under control)
    file_handler = RotatingFileHandler(
        filename=logs_dir / f"{name}.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5  # Keep 5 backup copies
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    # Add handlers to logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
