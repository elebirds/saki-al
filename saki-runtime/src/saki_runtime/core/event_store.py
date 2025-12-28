import json
import threading
from pathlib import Path
from typing import Iterator, Optional

import portalocker
from loguru import logger

from saki_runtime.schemas.events import EventEnvelope


class EventStore:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self._lock = threading.Lock()
        self._current_seq = self._init_seq()

    def _init_seq(self) -> int:
        """Initialize sequence number from the last line of the file."""
        if not self.file_path.exists():
            return 0
        
        try:
            with open(self.file_path, "rb") as f:
                # Efficiently read the last line? For MVP, just reading all lines or seeking might be okay.
                # But for large files, seeking is better.
                # Since lines are variable length, seeking to find the last newline is tricky but standard.
                # For MVP simplicity and robustness, let's just read the file line by line if it's not huge.
                # Or better: just trust the file size 0 means seq 0.
                # If file exists, we need to find the last seq.
                
                # Simple approach: Read last line using seek
                try:
                    f.seek(-2, 2)
                    while f.read(1) != b"\n":
                        f.seek(-2, 1)
                except OSError:
                    f.seek(0)
                
                last_line = f.readline().decode("utf-8")
                if not last_line:
                    return 0
                
                try:
                    event = json.loads(last_line)
                    return event.get("seq", 0)
                except json.JSONDecodeError:
                    logger.warning(f"Corrupted last line in {self.file_path}")
                    return 0
        except Exception as e:
            logger.error(f"Failed to init seq from {self.file_path}: {e}")
            return 0

    def next_seq(self) -> int:
        with self._lock:
            self._current_seq += 1
            return self._current_seq

    def append(self, event: EventEnvelope) -> None:
        """Append an event to the store with file locking."""
        # Ensure the event has the correct sequence number if not already set?
        # The contract says "seq 递增". The caller might have set it using next_seq().
        # We should probably validate or just trust the caller. 
        # But `next_seq` is provided by this class.
        
        line = event.model_dump_json() + "\n"
        
        # Use portalocker for cross-platform file locking
        try:
            with portalocker.Lock(self.file_path, mode="a", encoding="utf-8", timeout=5) as f:
                f.write(line)
                f.flush()
                # fsync is handled by portalocker/os usually on close, but flush is good.
                # portalocker.Lock opens the file.
        except portalocker.LockException:
            logger.error(f"Could not acquire lock for {self.file_path}")
            raise

    def tail(self, from_seq: int) -> Iterator[EventEnvelope]:
        """Read events from the store starting from a given sequence number."""
        if not self.file_path.exists():
            return

        # We open in read mode. We don't necessarily need a lock for reading if we accept
        # that we might read a partial line at the very end (though unlikely with append).
        # But to be safe, we can use a shared lock if portalocker supports it, 
        # or just read and handle JSON errors at the end.
        # For MVP, reading without lock is usually fine for tailing logs.
        
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    # We parse as dict first to check seq, then convert to model
                    if data.get("seq", 0) >= from_seq:
                        yield EventEnvelope.model_validate(data)
                except json.JSONDecodeError:
                    # Might happen if we read a half-written line
                    continue
