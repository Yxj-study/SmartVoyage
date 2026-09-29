import unittest

from SmartVoyage.main import parse_confirmation


class CoordinatorCliTest(unittest.TestCase):
    def test_confirmation_words(self):
        self.assertTrue(parse_confirmation("确认"))
        self.assertTrue(parse_confirmation("yes"))
        self.assertFalse(parse_confirmation("取消"))
        self.assertFalse(parse_confirmation("n"))

    def test_unknown_confirmation_returns_none(self):
        self.assertIsNone(parse_confirmation("再想想"))


if __name__ == "__main__":
    unittest.main()
