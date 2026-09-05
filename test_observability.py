import json
import tempfile
import unittest
from pathlib import Path

from core.observability import ObservabilityLogger


class TestObservabilityLogger(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = (
            Path(self.temp_dir.name)
            / "audit.jsonl"
        )
        self.logger = ObservabilityLogger(
            self.log_file
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def read_records(self):
        return [
            json.loads(line)
            for line in self.log_file.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

    def test_emit_creates_structured_event(self):
        record = self.logger.emit(
            "test_event",
            {"tool": "read_file"},
            request_id="req-1",
            status="success",
        )

        self.assertEqual(
            record["event"],
            "test_event",
        )
        self.assertEqual(
            record["request_id"],
            "req-1",
        )
        self.assertEqual(
            record["status"],
            "success",
        )
        self.assertIn(
            "timestamp",
            record,
        )

        records = self.read_records()
        self.assertEqual(len(records), 1)

    def test_request_id_is_generated(self):
        record = self.logger.emit(
            "test_event"
        )

        self.assertTrue(
            isinstance(
                record["request_id"],
                str,
            )
        )
        self.assertTrue(
            len(record["request_id"]) > 10
        )

    def test_recursive_secret_sanitization(self):
        data = {
            "api_key": "TOP-SECRET",
            "nested": {
                "token": "TOKEN-SECRET",
                "items": [
                    {
                        "password": "PASSWORD-SECRET",
                        "value": "safe",
                    }
                ],
            },
        }

        record = self.logger.emit(
            "security_test",
            data,
        )

        payload = record["data"]

        self.assertEqual(
            payload["api_key"],
            "[REDACTED]",
        )
        self.assertEqual(
            payload["nested"]["token"],
            "[REDACTED]",
        )
        self.assertEqual(
            payload["nested"]["items"][0]["password"],
            "[REDACTED]",
        )
        self.assertEqual(
            payload["nested"]["items"][0]["value"],
            "safe",
        )

    def test_long_strings_are_truncated(self):
        logger = ObservabilityLogger(
            self.log_file,
            max_value_length=128,
        )

        record = logger.emit(
            "truncate_test",
            {
                "value": "A" * 1000
            },
        )

        value = record["data"]["value"]

        self.assertTrue(
            value.endswith("[TRUNCATED]")
        )
        self.assertLessEqual(
            len(value),
            128 + len("...[TRUNCATED]"),
        )

    def test_start_and_finish_share_execution_id(self):
        execution_id, started, first = (
            self.logger.start_execution(
                "tool_start",
                request_id="req-42",
                data={"tool": "read_file"},
            )
        )

        second = self.logger.finish_execution(
            "tool_finished",
            started=started,
            request_id="req-42",
            execution_id=execution_id,
            status="success",
            data={"tool": "read_file"},
        )

        self.assertEqual(
            first["execution_id"],
            execution_id,
        )
        self.assertEqual(
            second["execution_id"],
            execution_id,
        )
        self.assertEqual(
            second["request_id"],
            "req-42",
        )
        self.assertEqual(
            second["status"],
            "success",
        )
        self.assertIn(
            "latency_ms",
            second,
        )
        self.assertGreaterEqual(
            second["latency_ms"],
            0,
        )

    def test_jsonl_persistence(self):
        self.logger.emit(
            "one",
            {"n": 1},
        )
        self.logger.emit(
            "two",
            {"n": 2},
        )

        records = self.read_records()

        self.assertEqual(
            len(records),
            2,
        )
        self.assertEqual(
            records[0]["event"],
            "one",
        )
        self.assertEqual(
            records[1]["event"],
            "two",
        )

    def test_invalid_event_is_rejected(self):
        with self.assertRaises(ValueError):
            self.logger.emit("")

    def test_invalid_data_is_rejected(self):
        with self.assertRaises(TypeError):
            self.logger.emit(
                "invalid",
                ["not", "a", "dict"],
            )


if __name__ == "__main__":
    unittest.main()
