from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DockerDeploymentTests(unittest.TestCase):
    def test_runtime_user_can_read_editable_source_tree(self) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("chown -R wenling:wenling /app /data", dockerfile)


if __name__ == "__main__":
    unittest.main()
