import unittest

from src.game.services import GameService
from src.models import BrothelState, Girl, Job


class EvaluateJobTests(unittest.TestCase):
    def setUp(self):
        self.service = GameService()
        self.job = Job(
            job_id="job-test",
            demand_main="Human",
            demand_level=1,
            demand_sub="VAGINAL",
            demand_sub_level=0,
            pay=50,
            difficulty=1,
        )

    def _make_girl(self, lust: int) -> Girl:
        girl = Girl(
            uid="g-test",
            base_id="base",
            name="Test Girl",
            rarity="R",
            lust=lust,
        )
        for name in girl.skills:
            girl.skills[name]["level"] = 2 if name == "Human" else 0
        return girl

    def test_brothel_lust_modifier_updates_lust_gate(self):
        girl = self._make_girl(lust=9)
        baseline = self.service.evaluate_job(girl, self.job)
        self.assertFalse(baseline["lust_ok"])
        self.assertFalse(baseline["can_attempt"])

        brothel = BrothelState(comfort_level=10, morale=100, cleanliness=90)
        adjusted = self.service.evaluate_job(girl, self.job, brothel)

        self.assertLess(adjusted["lust_cost"], baseline["lust_cost"])
        self.assertTrue(adjusted["lust_ok"])
        self.assertTrue(adjusted["can_attempt"])


if __name__ == "__main__":
    unittest.main()
