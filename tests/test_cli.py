from __future__ import annotations

import unittest

from autobot.cli import build_parser


class CLITests(unittest.TestCase):
    def test_web_host_public_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["web", "--host-public", "--port", "9091"])
        self.assertTrue(args.host_public)
        self.assertEqual(args.port, 9091)


if __name__ == "__main__":
    unittest.main()
