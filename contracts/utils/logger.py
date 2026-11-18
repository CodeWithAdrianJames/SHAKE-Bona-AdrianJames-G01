import logging
import tempfile
from pathlib import Path


def get_shared_logger(module_name: str) -> logging.Logger:
    """
    Sets up a logger that writes to a central temp log file and mutes the console.
    """
    log_file_path = Path(tempfile.gettempdir()) / "shake_engine.log"
    logger = logging.getLogger(module_name)

    if not logger.hasHandlers():
        logger.setLevel(logging.INFO)
        file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.propagate = False

    return logger
