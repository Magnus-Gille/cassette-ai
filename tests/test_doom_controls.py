"""Regression checks for the controls shipped by future DOOM v3 builds."""

import re
import unittest
from pathlib import Path


BUILD_DIR = Path(__file__).resolve().parents[1] / "payloads" / "doom" / "build"
BACKEND = BUILD_DIR / "src" / "doomgeneric_wasm_v3.c"
ASSEMBLERS = (
    BUILD_DIR / "assemble_html_v3.py",
    BUILD_DIR / "assemble_html_web.py",
)


class DoomControlsTest(unittest.TestCase):
    def test_ctrl_and_x_both_map_to_fire(self) -> None:
        source = BACKEND.read_text(encoding="utf-8")
        mappings = dict(
            re.findall(r"case\s+(\d+):\s+return\s+(\w+)\s*;", source)
        )

        self.assertEqual(mappings.get("17"), "KEY_FIRE", "Ctrl must remain fire")
        self.assertEqual(mappings.get("88"), "KEY_FIRE", "X must be Mac-safe fire")

    def test_future_builds_document_mac_safe_fire_key(self) -> None:
        for assembler in ASSEMBLERS:
            with self.subTest(assembler=assembler.name):
                source = assembler.read_text(encoding="utf-8")
                self.assertIn("ctrl/X fire (X: Mac-safe)", source)


if __name__ == "__main__":
    unittest.main()
