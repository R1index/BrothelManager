import unittest
from types import SimpleNamespace

from src.cogs.core import normalize_brothel_action


class BrothelActionNormalizationTests(unittest.TestCase):
    def test_expand_choice_is_preserved(self):
        choice = SimpleNamespace(value="expand")
        self.assertEqual(normalize_brothel_action(choice), "expand")

    def test_invalid_choice_defaults_to_view(self):
        choice = SimpleNamespace(value="invalid")
        self.assertEqual(normalize_brothel_action(choice), "view")

    def test_none_choice_defaults_to_view(self):
        self.assertEqual(normalize_brothel_action(None), "view")


if __name__ == "__main__":
    unittest.main()
