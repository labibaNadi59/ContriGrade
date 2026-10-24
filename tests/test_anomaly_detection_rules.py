
import os
import sys
import unittest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()

from academic.utils import detect_anomalies


class AnomalyDetectionRulesTests(unittest.TestCase):
    """
    Unit tests for cross-pillar and GitHub anomaly detection rules.
    Covers normal patterns, unusual patterns, and boundary cases with 6 concise test cases.
    """

    def test_01_normal_contribution_pattern_no_anomalies(self):
        """
        Normal Pattern: A student actively contributes across code, deliverables,
        and peer reviews with balanced scores. No anomalies should be detected.
        """
        anomalies = detect_anomalies(
            flags=[],
            final_score=78.5,
            active_weight_sum=100.0,
            gh_active=True,
            commit_count=12,
            gh_score=75.0,
            deliv_active=True,
            s_deliv_count=4,
            deliv_score=80.0,
            peer_active=True,
            peer_score=82.0,
            w_gh=40.0,
            w_deliv=30.0,
        )
        self.assertEqual(len(anomalies), 0)

    def test_02_unusual_pattern_github_integrity_flags(self):
        """
        Unusual Pattern (Rule A): Detects GitHub commit pattern anomalies:
        trivial/fluff commits, bulk code dumps, rapid-fire bursts, and general unusual activity.
        """
        flags = [
            "3 trivial/fluff commits (Very low LOC or short messages).",
            "1 massive code dumps (>1,000 additions in a single commit).",
            "2 rapid-fire bursts (Commits pushed within 2 minutes of each other).",
            "Unrecognized author email without mapped student account."
        ]
        anomalies = detect_anomalies(
            flags=flags,
            final_score=68.0,
            active_weight_sum=100.0,
            gh_active=True,
            commit_count=6,
            gh_score=65.0,
        )

        titles = [a['title'] for a in anomalies]
        self.assertIn("Trivial / Fluff Commit Pattern", titles)
        self.assertIn("Bulk Code Dump Detected", titles)
        self.assertIn("Rapid-Fire Commit Burst", titles)
        self.assertIn("Unusual GitHub Activity", titles)

        # Verify category and severities
        for a in anomalies:
            self.assertEqual(a['category'], "GitHub Integrity")
            if a['title'] == "Bulk Code Dump Detected":
                self.assertEqual(a['severity'], "high")
            else:
                self.assertEqual(a['severity'], "warning")

    def test_03_unusual_pattern_low_contribution_and_free_riding(self):
        """
        Unusual Pattern (Rule B): Detects free-riding when a student's overall weighted
        score is below 35% or when they have zero recorded work output in active pillars.
        """
        # Case 1: Overall weighted score < 35%
        low_score_anomalies = detect_anomalies(
            final_score=24.5,
            active_weight_sum=100.0,
            gh_active=True,
            commit_count=1,
            gh_score=15.0,
            deliv_active=True,
            s_deliv_count=1,
            deliv_score=20.0,
        )
        self.assertTrue(any(a['title'] == "Low Overall Contribution (Potential Free-Riding)" for a in low_score_anomalies))
        self.assertEqual(low_score_anomalies[0]['severity'], "high")
        self.assertEqual(low_score_anomalies[0]['category'], "Participation")

        # Case 2: Zero recorded work output (0 commits and 0 deliverables)
        zero_work_anomalies = detect_anomalies(
            final_score=36.0,
            active_weight_sum=100.0,
            gh_active=True,
            commit_count=0,
            deliv_active=True,
            s_deliv_count=0,
            peer_active=True,
            peer_score=90.0,
        )
        self.assertTrue(any(a['title'] == "Zero Recorded Work Output" for a in zero_work_anomalies))
        zero_work = next(a for a in zero_work_anomalies if a['title'] == "Zero Recorded Work Output")
        self.assertEqual(zero_work['severity'], "high")

    def test_04_unusual_pattern_cross_pillar_peer_mismatch(self):
        """
        Unusual Pattern (Rule C): Detects large discrepancies (>= 35%) between
        peer evaluation ratings and objective deliverables/GitHub output.
        """
        # Case 1: Peer rating inflation (High peer score, low objective output)
        inflation_anomalies = detect_anomalies(
            final_score=50.0,
            active_weight_sum=100.0,
            peer_active=True,
            peer_score=90.0,
            gh_active=True,
            gh_score=30.0,
            deliv_active=True,
            deliv_score=30.0,
        )
        self.assertTrue(any(a['title'] == "Peer Rating Inflation (High Peer vs. Low Output)" for a in inflation_anomalies))
        inflation = next(a for a in inflation_anomalies if a['title'] == "Peer Rating Inflation (High Peer vs. Low Output)")
        self.assertEqual(inflation['category'], "Cross-Pillar Mismatch")
        self.assertEqual(inflation['severity'], "warning")

        # Case 2: Peer rating deficit (High objective output, low peer rating)
        deficit_anomalies = detect_anomalies(
            final_score=60.0,
            active_weight_sum=100.0,
            peer_active=True,
            peer_score=30.0,
            gh_active=True,
            gh_score=85.0,
            deliv_active=True,
            deliv_score=85.0,
        )
        self.assertTrue(any(a['title'] == "Peer Rating Deficit (High Output vs. Low Peer Score)" for a in deficit_anomalies))
        deficit = next(a for a in deficit_anomalies if a['title'] == "Peer Rating Deficit (High Output vs. Low Peer Score)")
        self.assertEqual(deficit['category'], "Cross-Pillar Mismatch")

    def test_05_unusual_pattern_single_pillar_siloing(self):
        """
        Unusual Pattern (Rule D): Detects unbalanced siloing where a student works
        exclusively in code (>= 80% GH, 0% Deliverables) or exclusively in docs (>= 80% Deliverables, 0% GH).
        """
        # Case 1: Coding-only silo
        code_silo = detect_anomalies(
            final_score=65.0,
            active_weight_sum=100.0,
            gh_active=True,
            w_gh=40.0,
            gh_score=85.0,
            commit_count=10,
            deliv_active=True,
            w_deliv=30.0,
            deliv_score=0.0,
            s_deliv_count=0,
        )
        self.assertTrue(any(a['title'] == "Coding-Only Silo (Zero Non-Coding Tasks)" for a in code_silo))
        silo_entry = next(a for a in code_silo if a['title'] == "Coding-Only Silo (Zero Non-Coding Tasks)")
        self.assertEqual(silo_entry['category'], "Work Distribution")
        self.assertEqual(silo_entry['severity'], "warning")

        # Case 2: Non-coding silo
        docs_silo = detect_anomalies(
            final_score=55.0,
            active_weight_sum=100.0,
            gh_active=True,
            w_gh=40.0,
            gh_score=0.0,
            commit_count=0,
            deliv_active=True,
            w_deliv=30.0,
            deliv_score=90.0,
            s_deliv_count=5,
        )
        self.assertTrue(any(a['title'] == "Non-Coding Silo (Zero Code Contribution)" for a in docs_silo))
        docs_entry = next(a for a in docs_silo if a['title'] == "Non-Coding Silo (Zero Code Contribution)")
        self.assertEqual(docs_entry['category'], "Work Distribution")

    def test_06_boundary_cases_and_threshold_limits(self):
        """
        Boundary Cases: Verifies exact numeric cutoffs and edge conditions:
        - Free-riding threshold at 35.0% vs 34.9%
        - Peer evaluation gap threshold at exactly 35.0% vs 34.9%
        - Single-pillar siloing threshold at 80.0% vs 79.9%
        - Inactive weight sum edge condition (active_weight_sum = 0.0)
        """
        # 1. Final score threshold (< 35.0%)
        at_35 = detect_anomalies(final_score=35.0, active_weight_sum=100.0, gh_active=True, commit_count=1)
        self.assertFalse(any("Low Overall Contribution" in a['title'] for a in at_35))

        below_35 = detect_anomalies(final_score=34.9, active_weight_sum=100.0, gh_active=True, commit_count=1)
        self.assertTrue(any("Low Overall Contribution" in a['title'] for a in below_35))

        # 2. Peer mismatch gap threshold (>= 35.0%)
        # Diff = 35.0% (peer=75.0, obj=40.0) -> Triggers
        gap_at_35 = detect_anomalies(
            final_score=60.0,
            active_weight_sum=100.0,
            peer_active=True,
            peer_score=75.0,
            gh_active=True,
            gh_score=40.0,
        )
        self.assertTrue(any("Peer Rating Inflation" in a['title'] for a in gap_at_35))

        # Diff = 34.9% (peer=74.9, obj=40.0) -> Does not trigger
        gap_below_35 = detect_anomalies(
            final_score=60.0,
            active_weight_sum=100.0,
            peer_active=True,
            peer_score=74.9,
            gh_active=True,
            gh_score=40.0,
        )
        self.assertFalse(any("Peer Rating Inflation" in a['title'] for a in gap_below_35))

        # 3. Siloing threshold (>= 80.0%)
        # Score = 80.0% -> Triggers silo
        silo_80 = detect_anomalies(
            final_score=60.0,
            active_weight_sum=100.0,
            gh_active=True,
            w_gh=40.0,
            gh_score=80.0,
            commit_count=5,
            deliv_active=True,
            w_deliv=30.0,
            deliv_score=0.0,
        )
        self.assertTrue(any("Coding-Only Silo" in a['title'] for a in silo_80))

        # Score = 79.9% -> Does not trigger silo
        silo_79_9 = detect_anomalies(
            final_score=60.0,
            active_weight_sum=100.0,
            gh_active=True,
            w_gh=40.0,
            gh_score=79.9,
            commit_count=5,
            deliv_active=True,
            w_deliv=30.0,
            deliv_score=0.0,
        )
        self.assertFalse(any("Coding-Only Silo" in a['title'] for a in silo_79_9))

        # 4. Inactive weight sum edge condition (active_weight_sum = 0.0)
        no_evidence = detect_anomalies(final_score=0.0, active_weight_sum=0.0)
        self.assertEqual(len(no_evidence), 0)


if __name__ == '__main__':
    unittest.main()



