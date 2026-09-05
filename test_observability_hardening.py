import json
import tempfile
import unittest
from pathlib import Path

from core.observability import ObservabilityLogger


class TestObservabilityHardening(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "audit.jsonl"
        self.logger = ObservabilityLogger(self.log_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_complex_nested_data(self):
        record = self.logger.emit(
            "complex",
            {
                "numbers": (1, 2, 3),
                "nested": [
                    {
                        "API_KEY": "secret-1",
                        "api-key": "secret-2",
                        "values": [True, False, None, 3.14],
                    }
                ],
            },
        )

        data = record["data"]

        self.assertEqual(
            data["numbers"],
            [1, 2, 3],
        )
        self.assertEqual(
            data["nested"][0]["API_KEY"],
            "[REDACTED]",
        )
        self.assertEqual(
            data["nested"][0]["api-key"],
            "[REDACTED]",
        )
        self.assertEqual(
            data["nested"][0]["values"],
            [True, False, None, 3.14],
        )

    def test_unicode_data(self):
        record = self.logger.emit(
            "unicode_test",
            {
                "message": "مرحبا ALIX 🚀",
            },
        )

        self.assertEqual(
            record["data"]["message"],
            "مرحبا ALIX 🚀",
        )

        raw = self.log_file.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "مرحبا ALIX 🚀",
            raw,
        )

    def test_jsonl_every_line_is_valid_json(self):
        for index in range(10):
            self.logger.emit(
                f"event_{index}",
                {"index": index},
            )

        lines = self.log_file.read_text(
            encoding="utf-8"
        ).splitlines()

        self.assertEqual(
            len(lines),
            10,
        )

        for line in lines:
            parsed = json.loads(line)
            self.assertIsInstance(
                parsed,
                dict,
            )

    def test_sensitive_values_inside_multiple_levels(self):
        record = self.logger.emit(
            "deep_secret",
            {
                "level1": {
                    "level2": [
                        {
                            "credential": "SECRET",
                            "data": {
                                "authorization": "Bearer SECRET"
                            },
                        }
                    ]
                }
            },
        )

        deep = record["data"]["level1"]["level2"][0]

        self.assertEqual(
            deep["credential"],
            "[REDACTED]",
        )
        self.assertEqual(
            deep["data"]["authorization"],
            "[REDACTED]",
        )

    def test_non_json_native_values_are_stringified(self):
        class CustomObject:
            def __str__(self):
                return "custom-object"

        record = self.logger.emit(
            "custom",
            {
                "object": CustomObject(),
            },
        )

        self.assertEqual(
            record["data"]["object"],
            "custom-object",
        )


if __name__ == "__main__":
    unittest.main()
