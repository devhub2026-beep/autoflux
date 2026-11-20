import unittest
from unittest import mock

from retry import retry


class RetryTest(unittest.TestCase):
    def test_succeeds_first_time(self):
        calls = []

        @retry(attempts=3, delay=0)
        def ok():
            calls.append(1)
            return "yes"

        self.assertEqual(ok(), "yes")
        self.assertEqual(len(calls), 1)

    def test_retries_until_success(self):
        calls = []

        @retry(attempts=3, delay=0)
        def flaky():
            calls.append(1)
            if len(calls) < 3:
                raise ValueError("boom")
            return "ok"

        self.assertEqual(flaky(), "ok")
        self.assertEqual(len(calls), 3)

    def test_gives_up_after_attempts(self):
        calls = []

        @retry(attempts=2, delay=0)
        def always_bad():
            calls.append(1)
            raise ValueError("boom")

        with self.assertRaises(ValueError):
            always_bad()
        self.assertEqual(len(calls), 2)

    def test_backoff_delays_grow(self):
        delays = []
        calls = []

        @retry(attempts=3, delay=1.0, backoff=2.0)
        def bad():
            calls.append(1)
            raise ValueError("boom")

        with mock.patch("retry.time.sleep", side_effect=delays.append):
            with self.assertRaises(ValueError):
                bad()

        self.assertEqual(delays, [1.0, 2.0])

    def test_only_catches_listed_exception(self):
        calls = []

        @retry(attempts=3, delay=0, on=ValueError)
        def wrong_type():
            calls.append(1)
            raise KeyError("nope")

        with self.assertRaises(KeyError):
            wrong_type()
        self.assertEqual(len(calls), 1)

    def test_keeps_function_name(self):
        @retry(attempts=1, delay=0)
        def documented():
            """doc"""
            return 1

        self.assertEqual(documented.__name__, "documented")


if __name__ == "__main__":
    unittest.main()
