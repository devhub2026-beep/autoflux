from __future__ import annotations

import unittest
from pathlib import Path

from autoflux import config

from . import ScratchCase


class TestConfig(ScratchCase):
    def test_defaults_when_missing(self):
        cfg = config.load(Path("does-not-exist.toml"))
        self.assertEqual(cfg.task, "bugfix")
        self.assertEqual(cfg.limits.max_attempts, 5)
        self.assertEqual(cfg.limits.max_seconds, 1800.0)

    def test_load_custom(self):
        path = self.root / "c.toml"
        path.write_text(
            '[run]\ntask = "bugfix"\nmax_attempts = 2\ntarget_score = 0.9\nmax_seconds = 60\n'
            '[llm]\nmodel = "my-model"\n',
            encoding="utf-8",
        )
        cfg = config.load(path)
        self.assertEqual(cfg.limits.max_attempts, 2)
        self.assertAlmostEqual(cfg.limits.target_score, 0.9)
        self.assertEqual(cfg.limits.max_seconds, 60.0)
        self.assertEqual(cfg.llm.model, "my-model")


if __name__ == "__main__":
    unittest.main()
