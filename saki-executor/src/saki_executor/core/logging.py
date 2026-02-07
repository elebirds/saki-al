import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
        *,
        level: str,
        log_dir: str,
        log_file_name: str,
        max_bytes: int,
        backup_count: int,
) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    log_level = getattr(logging, (level or "INFO").upper(), logging.INFO)
    root_logger.setLevel(log_level)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(fmt)
    root_logger.addHandler(stream_handler)

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        filename=log_path / log_file_name,
        maxBytes=max(1, int(max_bytes)),
        backupCount=max(1, int(backup_count)),
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(fmt)
    root_logger.addHandler(file_handler)
