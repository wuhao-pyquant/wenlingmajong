from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryBoundaryTests(unittest.TestCase):
    def test_lan_source_does_not_import_training_or_cloudflare(self) -> None:
        forbidden = {"torch", "wenling_training", "dmc_model", "training_manager", "expert_selfplay", "cloudflared"}
        found: set[str] = set()
        for path in (ROOT / "src" / "wenling_lan_host").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    found.add(node.module)
        self.assertFalse({name for name in found if any(name == item or name.startswith(f"{item}.") for item in forbidden)})
