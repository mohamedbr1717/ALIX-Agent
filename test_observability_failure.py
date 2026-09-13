import tempfile
import unittest
from pathlib import Path

from core.observability import ObservabilityLogger


class TestObservabilityFailure(unittest.TestCase):

    def test_write_failure_is_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()

            log_file = log_dir / "audit.jsonl"

            logger = ObservabilityLogger(log_file)

            # تحويل ملف السجل إلى directory بعد إنشاء الـLogger.
            log_file.mkdir()

            with self.assertRaises(OSError):
                logger.emit(
                    "write_failure",
                    {"test": True},
                )


if __name__ == "__main__":
    unittest.main()
