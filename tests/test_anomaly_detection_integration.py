
import os
import sys
from datetime import timedelta
from unittest.mock import patch

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from academic.models import (
    Course, CourseSection, Project, Team, TeamMember,
    NonCodingDeliverable, DeliverableContribution,
    EvaluationCriterion, PeerEvaluation, PeerEvaluationScore
)
from academic.utils import calculate_project_contribution_scores


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AnomalyDetectionIntegrationTests(TestCase):
    """
    Integration tests for anomaly detection using contribution evidence.
    Acceptance criteria: Tests verify that the system detects anomalies
    using the correct student's evidence and score data.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Users
        self.instructor = User.objects.create_user(
            email="inst_integration@test.com",
            name="Prof. Anomaly Reviewer",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.coordinator = User.objects.create_user(
            email="coord_integration@test.com",
            name="Coord Grace",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.student_alice = User.objects.create_user(
            email="alice_evidence@test.com",
            name="Alice Walker",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_alice.github_username = "alice_dev"
        self.student_alice.save()

        self.student_bob = User.objects.create_user(
            email="bob_evidence@test.com",
            name="Bob Smith",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob.github_username = "bob_dev"
        self.student_bob.save()

        self.student_charlie = User.objects.create_user(
            email="charlie_evidence@test.com",
            name="Charlie Brown",
            role=User.Role.STUDENT,
            password="password123"
        )

        # Academic hierarchy
        self.course = Course.objects.create(
            course_code="CSE450",
            course_name="Software Engineering Capstone",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Sec 1",
            instructor=self.instructor
        )
        self.section.students.add(self.student_alice, self.student_bob, self.student_charlie)

        # Team 1 Project (weights: GH=40, Deliv=30, Peer=30)
        self.project_1 = Project.objects.create(
            section=self.section,
            title="Cloud Microservices Project",
            deadline=timezone.now() + timedelta(days=14),
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        self.team_1 = Team.objects.create(
            project=self.project_1,
            team_name="Alpha Team",
            github_repo_url="https://github.com/contrigrade/alpha-project"
        )
        TeamMember.objects.create(team=self.team_1, user=self.student_alice, role_in_team="Backend Lead")
        TeamMember.objects.create(team=self.team_1, user=self.student_bob, role_in_team="Frontend Dev")

        self.criterion = EvaluationCriterion.objects.create(
            project=self.project_1,
            name="Technical Contribution",
            max_score=5
        )

    # -------------------------------------------------------------------------
    # TEST 1: System detects no anomalies for balanced student evidence
    # -------------------------------------------------------------------------
    @patch('academic.utils.fetch_team_commits')
    def test_01_system_detects_no_anomalies_for_balanced_student_evidence(self, mock_gh):
        """Verifies clean status (0 anomalies) when student has balanced evidence across all pillars."""
        mock_gh.return_value = {
            'status': 'success',
            'commits': [
                {'sha': 'c1', 'author_username': 'alice_dev', 'message': 'Add user auth service', 'date': '2026-09-01T10:00:00Z', 'additions': 50, 'deletions': 10, 'is_merge': False},
                {'sha': 'c2', 'author_username': 'bob_dev', 'message': 'Add dashboard components', 'date': '2026-09-01T11:00:00Z', 'additions': 45, 'deletions': 12, 'is_merge': False},
            ]
        }
        # 1 verified deliverable each
        d1 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_alice, title="API Design", link="https://docs.p1.io")
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_alice, contribution_area="Auth API", status='VERIFIED')
        d2 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_bob, title="UI Wireframes", link="https://figma.p1.io")
        DeliverableContribution.objects.create(deliverable=d2, student=self.student_bob, contribution_area="Wireframes", status='VERIFIED')

        # Mutual peer ratings 4/5 (80.0%)
        eval_b_to_a = PeerEvaluation.objects.create(team=self.team_1, evaluator=self.student_bob, evaluatee=self.student_alice)
        PeerEvaluationScore.objects.create(evaluation=eval_b_to_a, criterion=self.criterion, score=4)
        eval_a_to_b = PeerEvaluation.objects.create(team=self.team_1, evaluator=self.student_alice, evaluatee=self.student_bob)
        PeerEvaluationScore.objects.create(evaluation=eval_a_to_b, criterion=self.criterion, score=4)

        results = calculate_project_contribution_scores(self.project_1, target_team=self.team_1)
        alice_data = next(m for m in results['master_data'] if m['student_id'] == self.student_alice.pk)

        self.assertEqual(len(alice_data['anomalies']), 0)
        self.assertEqual(alice_data['anomaly_count'], 0)

        # Verify UI renders Clean state
        self.client.force_login(self.instructor)
        resp = self.client.get(reverse('student_evidence_detail', kwargs={'team_id': self.team_1.pk, 'student_id': self.student_alice.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No Unusual Contribution Patterns Detected")
        self.assertContains(resp, "Verified Clean")

    # -------------------------------------------------------------------------
    # TEST 2: System detects GitHub integrity anomalies from commit evidence
    # -------------------------------------------------------------------------
    @patch('academic.utils.fetch_team_commits')
    def test_02_system_detects_github_integrity_anomalies_from_commit_evidence(self, mock_gh):
        """Verifies Rule A detects trivial fluff commits and massive dumps from raw commit records."""
        mock_gh.return_value = {
            'status': 'success',
            'commits': [
                # Trivial/fluff commit (additions+deletions < 3 and message < 5 chars)
                {'sha': 'c1', 'author_username': 'alice_dev', 'message': 'fix', 'date': '2026-09-01T10:00:00Z', 'additions': 1, 'deletions': 0, 'is_merge': False},
                # Massive code dump (> 1000 additions)
                {'sha': 'c2', 'author_username': 'alice_dev', 'message': 'Massive zip upload', 'date': '2026-09-01T12:00:00Z', 'additions': 1500, 'deletions': 0, 'is_merge': False},
                # Normal commit for Bob
                {'sha': 'c3', 'author_username': 'bob_dev', 'message': 'Iterative feature commit', 'date': '2026-09-01T14:00:00Z', 'additions': 60, 'deletions': 10, 'is_merge': False},
            ]
        }
        results = calculate_project_contribution_scores(self.project_1, target_team=self.team_1)
        alice_data = next(m for m in results['master_data'] if m['student_id'] == self.student_alice.pk)

        titles = [a['title'] for a in alice_data['anomalies']]
        self.assertIn("Trivial / Fluff Commit Pattern", titles)
        self.assertIn("Bulk Code Dump Detected", titles)

        # Verify UI renders flags and explanations
        self.client.force_login(self.instructor)
        resp = self.client.get(reverse('student_evidence_detail', kwargs={'team_id': self.team_1.pk, 'student_id': self.student_alice.pk}))
        self.assertContains(resp, "Detected Contribution Anomalies")
        self.assertContains(resp, "Bulk Code Dump Detected")
        self.assertContains(resp, "Pushing over 1,000 lines in a single commit")

    # -------------------------------------------------------------------------
    # TEST 3: System detects low contribution free-riding from low evidence
    # -------------------------------------------------------------------------
    @patch('academic.utils.fetch_team_commits')
    def test_03_system_detects_low_contribution_free_riding_from_low_evidence(self, mock_gh):
        """Verifies Rule B flags free-riding when a student has negligible output while team is active."""
        # Team Member Charlie added to Team 1
        TeamMember.objects.create(team=self.team_1, user=self.student_charlie, role_in_team="QA")

        # Alice has high GitHub activity, Bob and Charlie have 0 commits
        mock_gh.return_value = {
            'status': 'success',
            'commits': [
                {'sha': 'c1', 'author_username': 'alice_dev', 'message': 'Build complete core engine', 'date': '2026-09-01T10:00:00Z', 'additions': 300, 'deletions': 50, 'is_merge': False},
            ]
        }
        # Alice has 2 verified deliverables, Charlie has 0
        d1 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_alice, title="Sprint Plan", link="https://docs.p1.io")
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_alice, contribution_area="Scrum", status='VERIFIED')

        # Alice rates Charlie poorly (1/5)
        eval_a_to_c = PeerEvaluation.objects.create(team=self.team_1, evaluator=self.student_alice, evaluatee=self.student_charlie)
        PeerEvaluationScore.objects.create(evaluation=eval_a_to_c, criterion=self.criterion, score=1)

        results = calculate_project_contribution_scores(self.project_1, target_team=self.team_1)
        charlie_data = next(m for m in results['master_data'] if m['student_id'] == self.student_charlie.pk)

        # Charlie's final score is very low (< 35%), triggering free-riding anomaly
        self.assertLess(charlie_data['final_score'], 35.0)
        self.assertTrue(any(a['title'] == "Low Overall Contribution (Potential Free-Riding)" for a in charlie_data['anomalies']))

        # Verify UI renders High Severity warning
        self.client.force_login(self.instructor)
        resp = self.client.get(reverse('student_evidence_detail', kwargs={'team_id': self.team_1.pk, 'student_id': self.student_charlie.pk}))
        self.assertContains(resp, "Low Overall Contribution (Potential Free-Riding)")
        self.assertContains(resp, "below the 35% threshold")

    # -------------------------------------------------------------------------
    # TEST 4: System detects peer inflation from high peer and low objective evidence
    # -------------------------------------------------------------------------
    def test_04_system_detects_peer_inflation_from_high_peer_and_low_evidence(self):
        """Verifies Rule C detects Peer Rating Inflation when peer ratings wildly exceed work output."""
        # Deliverables active for team: Bob has 2 verified deliverables
        d1 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_bob, title="Design Specs", link="https://spec.io")
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_bob, contribution_area="Specs", status='VERIFIED')
        d2 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_bob, title="Threat Model", link="https://threat.io")
        DeliverableContribution.objects.create(deliverable=d2, student=self.student_bob, contribution_area="Threats", status='VERIFIED')

        # Alice has 0 deliverables and 0 commits (objective output = 0%)
        # But Bob gives Alice a maximum rating: 5/5 (100% peer evaluation)
        eval_b_to_a = PeerEvaluation.objects.create(team=self.team_1, evaluator=self.student_bob, evaluatee=self.student_alice)
        PeerEvaluationScore.objects.create(evaluation=eval_b_to_a, criterion=self.criterion, score=5)

        # Peer score = 100%, Objective average = 0% -> Gap = 100% (>= 35%)
        results = calculate_project_contribution_scores(self.project_1, target_team=self.team_1)
        alice_data = next(m for m in results['master_data'] if m['student_id'] == self.student_alice.pk)

        inflation_anomalies = [a for a in alice_data['anomalies'] if a['title'] == "Peer Rating Inflation (High Peer vs. Low Output)"]
        self.assertEqual(len(inflation_anomalies), 1)
        self.assertEqual(inflation_anomalies[0]['category'], "Cross-Pillar Mismatch")

        # Verify UI renders the Peer Inflation alert
        self.client.force_login(self.instructor)
        resp = self.client.get(reverse('student_evidence_detail', kwargs={'team_id': self.team_1.pk, 'student_id': self.student_alice.pk}))
        self.assertContains(resp, "Peer Rating Inflation (High Peer vs. Low Output)")
        self.assertContains(resp, "Cross-Pillar Mismatch")

    # -------------------------------------------------------------------------
    # TEST 5: System detects peer deficit from high evidence and low peer score
    # -------------------------------------------------------------------------
    def test_05_system_detects_peer_deficit_from_high_evidence_and_low_peer(self):
        """Verifies Rule C detects Peer Rating Deficit when objective deliverables output is high but peer rating is harsh."""
        # Alice has 2 verified deliverables; Bob has 2 verified deliverables (expected = 2.0)
        d1 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_alice, title="API Architecture", link="https://arch.io")
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_alice, contribution_area="API", status='VERIFIED')
        d2 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_alice, title="DB Migration", link="https://db.io")
        DeliverableContribution.objects.create(deliverable=d2, student=self.student_alice, contribution_area="DB", status='VERIFIED')

        d3 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_bob, title="Task B1", link="https://b1.io")
        DeliverableContribution.objects.create(deliverable=d3, student=self.student_bob, contribution_area="B1", status='VERIFIED')
        d4 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_bob, title="Task B2", link="https://b2.io")
        DeliverableContribution.objects.create(deliverable=d4, student=self.student_bob, contribution_area="B2", status='VERIFIED')

        # Alice achieved 80% deliverables score, but Bob harshly rates her 1/5 (20.0%)
        eval_b_to_a = PeerEvaluation.objects.create(team=self.team_1, evaluator=self.student_bob, evaluatee=self.student_alice)
        PeerEvaluationScore.objects.create(evaluation=eval_b_to_a, criterion=self.criterion, score=1)

        # Gap = 80.0% - 20.0% = 60.0% >= 35.0%
        results = calculate_project_contribution_scores(self.project_1, target_team=self.team_1)
        alice_data = next(m for m in results['master_data'] if m['student_id'] == self.student_alice.pk)

        deficit_anomalies = [a for a in alice_data['anomalies'] if a['title'] == "Peer Rating Deficit (High Output vs. Low Peer Score)"]
        self.assertEqual(len(deficit_anomalies), 1)

        # Verify UI renders the Peer Deficit alert
        self.client.force_login(self.instructor)
        resp = self.client.get(reverse('student_evidence_detail', kwargs={'team_id': self.team_1.pk, 'student_id': self.student_alice.pk}))
        self.assertContains(resp, "Peer Rating Deficit (High Output vs. Low Peer Score)")

    # -------------------------------------------------------------------------
    # TEST 6: Evidence isolation - anomalies strictly mapped to correct student & team
    # -------------------------------------------------------------------------
    @patch('academic.utils.fetch_team_commits')
    def test_06_evidence_isolation_anomalies_strictly_mapped_to_correct_student_and_team(self, mock_gh):
        """Verifies anomalies detected for Student A do not leak to clean teammates or other teams."""
        # Alice has fluff commits; Bob has clean commits
        mock_gh.return_value = {
            'status': 'success',
            'commits': [
                {'sha': 'c1', 'author_username': 'alice_dev', 'message': 'wip', 'date': '2026-09-01T10:00:00Z', 'additions': 1, 'deletions': 0, 'is_merge': False},
                {'sha': 'c2', 'author_username': 'bob_dev', 'message': 'Implement database connection pool', 'date': '2026-09-01T11:00:00Z', 'additions': 75, 'deletions': 10, 'is_merge': False},
            ]
        }
        # Bob has 1 verified deliverable; mutual peer reviews 4/5
        d_bob = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_bob, title="Bob Task", link="https://bob.io")
        DeliverableContribution.objects.create(deliverable=d_bob, student=self.student_bob, contribution_area="Dev", status='VERIFIED')

        eval_b_to_a = PeerEvaluation.objects.create(team=self.team_1, evaluator=self.student_bob, evaluatee=self.student_alice)
        PeerEvaluationScore.objects.create(evaluation=eval_b_to_a, criterion=self.criterion, score=4)
        eval_a_to_b = PeerEvaluation.objects.create(team=self.team_1, evaluator=self.student_alice, evaluatee=self.student_bob)
        PeerEvaluationScore.objects.create(evaluation=eval_a_to_b, criterion=self.criterion, score=4)

        results = calculate_project_contribution_scores(self.project_1, target_team=self.team_1)
        members = {m['student_id']: m for m in results['master_data']}

        # Alice is flagged with fluff commit anomaly
        self.assertGreater(len(members[self.student_alice.pk]['anomalies']), 0)
        # Bob has ZERO anomalies
        self.assertEqual(len(members[self.student_bob.pk]['anomalies']), 0)

        # Instructor opens Team Overview page
        self.client.force_login(self.instructor)
        resp_team = self.client.get(reverse('team_contribution_scores', kwargs={'team_id': self.team_1.pk}))
        self.assertContains(resp_team, "Detected Anomalies")
        self.assertContains(resp_team, "Flagged")

        # Instructor opens Bob's evidence page - verify Clean state without anomaly alerts
        resp_bob = self.client.get(reverse('student_evidence_detail', kwargs={'team_id': self.team_1.pk, 'student_id': self.student_bob.pk}))
        self.assertContains(resp_bob, "No Unusual Contribution Patterns Detected")
        self.assertNotContains(resp_bob, "Trivial / Fluff Commit Pattern")

