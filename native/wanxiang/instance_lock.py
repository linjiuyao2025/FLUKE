from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLockFile


class PlannerDatabaseInstanceLock:
    """Keep two desktop processes from writing the same local workspace DB."""

    def __init__(self, database_path: str | Path) -> None:
        database = Path(database_path).expanduser().resolve()
        self.lock_path = database.with_name(database.name + ".instance.lock")
        self._lock = QLockFile(str(self.lock_path))

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        return bool(self._lock.tryLock(0))

    def release(self) -> None:
        if self._lock.isLocked():
            self._lock.unlock()
