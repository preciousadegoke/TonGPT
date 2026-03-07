import logging
import re
from logging.handlers import RotatingFileHandler

_PII_PATTERNS = [
    (re.compile(r'\b(EQ|UQ)[A-Za-z0-9_-]{46}\b'), '[WALLET]'),
    (re.compile(r'(user_id|telegram_id)[=:\s]+\d{6,12}'), r'\1=[ID]'),
    (re.compile(r'sk-[A-Za-z0-9\-]{20,}'), '[KEY]'),
]


class PIIFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._scrub(str(record.msg))
        if isinstance(record.args, dict):
            record.args = {k: self._scrub(str(v)) for k, v in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(self._scrub(str(a)) for a in record.args)
        return True

    def _scrub(self, text: str) -> str:
        for pattern, replacement in _PII_PATTERNS:
            text = pattern.sub(replacement, text)
        return text


def configure_logging(log_file: str = "bot.log"):
    pii = PIIFilter()
    fh = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.addFilter(pii)
    ch = logging.StreamHandler()
    ch.addFilter(pii)
    ch.setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[fh, ch],
    )

