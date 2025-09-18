import unittest

from src.models import BrothelState, Job, PROMOTE_COINS_PER_RENOWN, now_ts


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


class BrothelHygieneTests(unittest.TestCase):
    def test_hygiene_mitigates_decay_and_penalties(self):
        ticks = 6
        reference_ts = now_ts() - 900 * ticks
        low = BrothelState(
            hygiene_level=1,
            cleanliness=35,
            morale=70,
            renown=120,
            last_tick_ts=reference_ts,
        )
        high = BrothelState(
            hygiene_level=8,
            cleanliness=35,
            morale=70,
            renown=120,
            last_tick_ts=reference_ts,
        )

        low.apply_decay()
        high.apply_decay()

        low_loss = 35 - low.cleanliness
        high_loss = 35 - high.cleanliness

        self.assertGreaterEqual(high.cleanliness, low.cleanliness)
        self.assertLessEqual(high_loss, low_loss)
        self.assertGreaterEqual(high.morale, low.morale)
        self.assertGreaterEqual(high.renown, low.renown)

    def test_decay_residual_accumulates_with_frequent_calls(self):
        brothel = BrothelState(hygiene_level=9, cleanliness=90)

        for _ in range(10):
            brothel.last_tick_ts = now_ts() - 900
            brothel.apply_decay()

        self.assertLess(brothel.cleanliness, 90)
        self.assertLessEqual(brothel.cleanliness, 85)

    def test_hygiene_improves_maintenance(self):
        low = BrothelState(hygiene_level=1, cleanliness=40, upkeep_pool=0)
        high = BrothelState(hygiene_level=7, cleanliness=40, upkeep_pool=0)

        low_result = low.maintain(120)
        high_result = high.maintain(120)

        self.assertGreater(high_result["cleanliness"], low_result["cleanliness"])
        self.assertGreaterEqual(high.cleanliness, low.cleanliness)
        self.assertGreaterEqual(high_result["morale"], low_result["morale"])

    def test_hygiene_reduces_job_wear(self):
        job = Job(
            job_id="test",
            demand_main="Human",
            demand_level=1,
            demand_sub="VAGINAL",
            demand_sub_level=1,
            pay=100,
            difficulty=3,
        )
        low = BrothelState(hygiene_level=1, cleanliness=85)
        high = BrothelState(hygiene_level=9, cleanliness=85)

        low.register_job_outcome(success=True, injured=True, job=job, reward=200)
        high.register_job_outcome(success=True, injured=True, job=job, reward=200)

        low_loss = 85 - low.cleanliness
        high_loss = 85 - high.cleanliness

        self.assertGreaterEqual(high.cleanliness, low.cleanliness)
        self.assertLessEqual(high_loss, low_loss)


class BrothelJobOutcomeTests(unittest.TestCase):
    def test_register_job_outcome_returns_deltas(self):
        job = Job(
            job_id="delta-test",
            demand_main="Human",
            demand_level=1,
            demand_sub="VAGINAL",
            demand_sub_level=1,
            pay=150,
            difficulty=2,
        )
        brothel = BrothelState(
            hygiene_level=5,
            cleanliness=78,
            morale=65,
            renown=90,
            upkeep_pool=120,
        )

        cleanliness_before = brothel.cleanliness
        morale_before = brothel.morale
        renown_before = brothel.renown
        upkeep_before = brothel.upkeep_pool

        deltas = brothel.register_job_outcome(success=True, injured=True, job=job, reward=180)

        self.assertIsInstance(deltas, dict)
        self.assertIn("cleanliness", deltas)
        self.assertIn("morale", deltas)
        self.assertIn("renown", deltas)
        self.assertIn("upkeep", deltas)

        self.assertEqual(deltas["cleanliness"], brothel.cleanliness - cleanliness_before)
        self.assertEqual(deltas["morale"], brothel.morale - morale_before)
        self.assertEqual(deltas["renown"], brothel.renown - renown_before)
        self.assertEqual(deltas["upkeep"], brothel.upkeep_pool - upkeep_before)

        self.assertLessEqual(deltas["cleanliness"], 0)
        self.assertGreaterEqual(deltas["upkeep"], 0)

if __name__ == "__main__":
    unittest.main()
