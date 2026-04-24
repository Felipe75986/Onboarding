import json
import re
from datetime import datetime
from pathlib import Path


class FileLogger:
    """
    Structured JSONL file logger compatible with Grafana/Loki/Elasticsearch.

    Each log entry is written as a single JSON line with fixed fields:
    timestamp, level, message, user, process_name — plus any extra kwargs.

    File path is resolved on every write, so log rotation across midnight
    happens automatically without restarting the process.
    """

    def __init__(self, logs_dir: str | Path, process_name: str, username: str) -> None:
        self._logs_dir = Path(logs_dir)
        self._process_name = process_name
        self._username = username
        self._safe_username = re.sub(r'[^\w\-.]', '_', username)
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def info(self, message: str, **kwargs) -> None:
        self._write('INFO', message, **kwargs)

    def warn(self, message: str, **kwargs) -> None:
        self._write('WARN', message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        if 'status' not in kwargs:
            kwargs['status'] = 'FAILED'
        self._write('ERROR', message, **kwargs)

    def debug(self, message: str, **kwargs) -> None:
        self._write('DEBUG', message, **kwargs)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _current_log_path(self) -> Path:
        date_str = datetime.now().strftime('%Y-%m-%d')
        return self._logs_dir / f"{date_str}_{self._safe_username}.log"

    def _write(self, level: str, message: str, **kwargs) -> None:
        entry = {
            'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'level': level,
            'message': message,
            'user': self._username,
            'process_name': self._process_name,
        }
        entry.update(kwargs)

        log_path = self._current_log_path()
        with log_path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
