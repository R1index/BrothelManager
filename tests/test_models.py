import unittest

from src.models import BrothelState, PROMOTE_COINS_PER_RENOWN


class BrothelPromotionTests(unittest.TestCase):
    def test_small_investment_does_not_grant_renown(self):
        brothel = BrothelState(renown=120, morale=70)
        result = brothel.promote(PROMOTE_COINS_PER_RENOWN - 1)

        self.assertEqual(result["renown"], 0)
        self.assertEqual(brothel.renown, 120)

    def test_threshold_investment_grants_renown(self):
        brothel = BrothelState(renown=120, morale=70)
        result = brothel.promote(PROMOTE_COINS_PER_RENOWN)

        self.assertEqual(result["renown"], 1)
        self.assertEqual(brothel.renown, 121)


if __name__ == "__main__":
    unittest.main()
