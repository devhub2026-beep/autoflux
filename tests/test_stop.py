from __future__ import annotations

import unittest

from autoflux.config import Limits
from autoflux.stop import StopPolicy


def policy(**kw) -> StopPolicy:
    base = {"max_steps": 20, "max_attempts": 10, "target_score": 1.0, "no_improve_limit": 2}
    base.update(kw)
    return StopPolicy(Limits(**base))


class TestStopPolicy(unittest.TestCase):
    def test_no_attempts_keeps_going(self):
        self.assertIsNone(policy().check(attempts=[], steps_used=0))

    def test_target_reached(self):
        reason = policy().check(attempts=[0.4, 1.0], steps_used=5)
        self.assertIsNotNone(reason)
        self.assertIn("达标", reason)

    def test_max_attempts(self):
        reason = policy(max_attempts=3).check(attempts=[0.1, 0.2, 0.3], steps_used=5)
        self.assertIn("尝试次数用尽", reason)

    def test_no_improvement(self):
        reason = policy(no_improve_limit=2).check(
            attempts=[0.2, 0.5, 0.5, 0.5], steps_used=9
        )
        self.assertIn("无提升", reason)

    def test_improving_does_not_stop(self):
        self.assertIsNone(policy(no_improve_limit=2).check(attempts=[0.2, 0.5, 0.9], steps_used=9))

    def test_steps_exhausted(self):
        reason = policy().check(attempts=[], steps_used=20)
        self.assertIn("步数用尽", reason)


if __name__ == "__main__":
    unittest.main()
