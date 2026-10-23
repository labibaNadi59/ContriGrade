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
class EvidenceAndComponentScoreDisplayTests(TestCase):
    """
    Unit tests for evidence and component score display logic.
    Verifies that component scores, policy weights, and calculated totals
    are correctly computed and displayed, with boundary value coverage.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        # 1. Create Users
        self.coordinator = User.objects.create_user(
            email="coord_evidence@test.com",
            name="Coordinator Vance",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="instructor_evidence@test.com",
            name="Dr. Alan Turing",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.admin = User.objects.create_user(
            email="admin_evidence@test.com",
            name="System Admin",
            role=User.Role.ADMIN,
            password="password123"
        )
        self.student_a = User.objects.create_user(
            email="student_a@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_a.github_username = "alice_dev"
        self.student_a.save()

        self.student_b = User.objects.create_user(
            email="student_b@test.com",
            name="Bob Teammate",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_b.github_username = "bob_dev"
        self.student_b.save()
        self.outside_student = User.objects.create_user(
            email="outsider@test.com",
            name="Outside Student",
            role=User.Role.STUDENT,
            password="password123"
        )

        # 2. Academic Structure
        self.course = Course.objects.create(
            course_code="CSE412",
            course_name="Software Quality & Architecture",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student_a, self.student_b)

        # 3. Project with standard weights: 40% GitHub, 30% Deliverables, 30% Peer
        self.project = Project.objects.create(
            section=self.section,
            title="Cloud Microservices Platform",
            description="Term project building scalable architecture",
            deadline=timezone.now() + timedelta(days=14),
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )

        # 4. Team with Linked GitHub Repo
        self.team = Team.objects.create(
            project=self.project,
            team_name="Backend Squad",
            github_repo_url="https://github.com/contrigrade/backend-squad"
        )
        self.member_a = TeamMember.objects.create(team=self.team, user=self.student_a, role_in_team="Lead Dev")
        self.member_b = TeamMember.objects.create(team=self.team, user=self.student_b, role_in_team="Backend Dev")

        # 5. Peer Evaluation Criterion
        self.criterion = EvaluationCriterion.objects.create(
            project=self.project,
            name="Technical Contribution",
            max_score=5
        )

        # URL for viewing Alice's evidence
        self.evidence_url = reverse(
            'student_evidence_detail',
            kwargs={'team_id': self.team.pk, 'student_id': self.student_a.pk}
        )

    def _mock_github_analytics(self, impact_a=10, impact_b=10, commits_a=5, commits_b=5):
        """Helper to return consistent GitHub contribution analytics for tests."""
        return {
            'total_commits': commits_a + commits_b,
            'mapped_students': {
                self.student_a.pk: {
                    'name': self.student_a.name,
                    'github_username': self.student_a.github_username,
                    'role': 'Lead Dev',
                    'commit_count': commits_a,
                    'total_additions': 100,
                    'total_deletions': 20,
                    'impact_score': impact_a,
                    'flags': []
                },
                self.student_b.pk: {
                    'name': self.student_b.name,
                    'github_username': self.student_b.github_username,
                    'role': 'Backend Dev',
                    'commit_count': commits_b,
                    'total_additions': 80,
                    'total_deletions': 15,
                    'impact_score': impact_b,
                    'flags': []
                }
            }
        }

    # =========================================================================
    # TEST 1: Standard Component Scores, Weights, and Total Display
    # =========================================================================
    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_standard_components_scores_weights_and_calculated_total_display(self, mock_fetch, mock_analyze):
        """Verifies component scores, policy weights, calculated totals, and evidence are displayed correctly."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        mock_analyze.return_value = self._mock_github_analytics(impact_a=10, impact_b=10)

        # Deliverables: 1 verified task for Alice, 1 for Bob (total=2, avg=1.0 -> raw=(1/1)*80 = 80.0%)
        deliv1 = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_a,
            title="System Architecture Document",
            link="https://docs.contrigrade.io/arch"
        )
        DeliverableContribution.objects.create(
            deliverable=deliv1,
            student=self.student_a,
            contribution_area="Database Schema",
            status='VERIFIED'
        )
        deliv2 = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_b,
            title="API Specifications",
            link="https://docs.contrigrade.io/api"
        )
        DeliverableContribution.objects.create(
            deliverable=deliv2,
            student=self.student_b,
            contribution_area="Endpoints Design",
            status='VERIFIED'
        )

        # Peer Evaluation: Bob gives Alice 4/5 (4/5 = 80.0%)
        eval_ba = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_b, evaluatee=self.student_a)
        PeerEvaluationScore.objects.create(evaluation=eval_ba, criterion=self.criterion, score=4)

        # Verify underlying logic calculation directly
        results = calculate_project_contribution_scores(self.project, target_team=self.team)
        alice_data = next(m for m in results['master_data'] if m['student_id'] == self.student_a.pk)

        # Math checks:
        # GitHub: (10 impact / 10 avg) * 80 = 80.0%, pts = (80 * 40)/100 = 32.0 pts
        # Deliverables: (1 task / 1 avg) * 80 = 80.0%, pts = (80 * 30)/100 = 24.0 pts
        # Peer: (4 / 5) * 100 = 80.0%, pts = (80 * 30)/100 = 24.0 pts
        # Final Total: 32.0 + 24.0 + 24.0 = 80.0%
        self.assertEqual(alice_data['github_score'], 80.0)
        self.assertEqual(alice_data['deliverables_score'], 80.0)
        self.assertEqual(alice_data['peer_score'], 80.0)
        self.assertEqual(alice_data['pts_github'], 32.0)
        self.assertEqual(alice_data['pts_deliverables'], 24.0)
        self.assertEqual(alice_data['pts_peer'], 24.0)
        self.assertEqual(alice_data['final_score'], 80.0)

        # Verify View and Rendered HTML Display
        self.client.force_login(self.instructor)
        resp = self.client.get(self.evidence_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Header summary & Calculated Total
        self.assertIn("GitHub: 32.0 pts", content)
        self.assertIn("Tasks: 24.0 pts", content)
        self.assertIn("Peer: 24.0 pts", content)
        self.assertIn("80.0%", content)
        self.assertIn("Calculated Total", content)

        # Component Scores and Weights
        self.assertIn("× 40%", content)  # GitHub policy weight
        self.assertIn("× 30%", content)  # Deliverables & Peer policy weights
        self.assertIn("32.0 pts", content)
        self.assertIn("24.0 pts", content)

        # Evidence Display
        self.assertIn("System Architecture Document", content)
        self.assertIn("Database Schema", content)
        self.assertIn("Technical Contribution", content)
        self.assertIn("4/5", content)
        self.assertIn("alice_dev", content)

    # =========================================================================
    # TEST 2: Boundary Value - Zero Contributions Yields Zero Scores
    # =========================================================================
    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_boundary_zero_contributions_displays_zero_scores(self, mock_fetch, mock_analyze):
        """Boundary test: Zero student contributions produce 0.0% component scores and 0.0% total."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        # Bob has all impact (20), Alice has 0 impact
        mock_analyze.return_value = self._mock_github_analytics(impact_a=0, impact_b=20, commits_a=0, commits_b=10)

        # Bob has 1 verified deliverable, Alice has 0
        deliv = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_b,
            title="Design System",
            link="https://docs.contrigrade.io/design"
        )
        DeliverableContribution.objects.create(
            deliverable=deliv,
            student=self.student_b,
            contribution_area="Component UI",
            status='VERIFIED'
        )

        # Bob evaluates Alice with 0/5
        eval_ba = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_b, evaluatee=self.student_a)
        PeerEvaluationScore.objects.create(evaluation=eval_ba, criterion=self.criterion, score=0)

        self.client.force_login(self.instructor)
        resp = self.client.get(self.evidence_url)
        content = resp.content.decode('utf-8')

        # Underlying calculation and display both show 0.0%
        self.assertEqual(resp.context['score_data']['github_score'], 0.0)
        self.assertEqual(resp.context['score_data']['deliverables_score'], 0.0)
        self.assertEqual(resp.context['score_data']['peer_score'], 0.0)
        self.assertEqual(resp.context['score_data']['final_score'], 0.0)
        self.assertIn("0.0%", content)
        self.assertIn("0.0 pts", content)

    # =========================================================================
    # TEST 3: Boundary Value - Maximum Contributions Capped at 100%
    # =========================================================================
    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_boundary_maximum_contributions_capped_at_hundred(self, mock_fetch, mock_analyze):
        """Boundary test: Scores greatly exceeding expected averages are strictly capped at 100.0%."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        # Alice impact=50, Bob impact=10 (team avg=30 -> raw=(50/30)*80 = 133.3% -> capped at 100.0%)
        mock_analyze.return_value = self._mock_github_analytics(impact_a=50, impact_b=10)

        # Deliverables: Alice has 4 verified tasks, Bob has 1 (team avg=2.5 -> raw=(4/2.5)*80 = 128.0% -> capped to 100.0%)
        for i in range(4):
            d = NonCodingDeliverable.objects.create(
                team=self.team, submitted_by=self.student_a,
                title=f"Deliverable {i}", link=f"https://docs.contrigrade.io/{i}"
            )
            DeliverableContribution.objects.create(
                deliverable=d, student=self.student_a,
                contribution_area=f"Area {i}", status='VERIFIED'
            )

        d_bob = NonCodingDeliverable.objects.create(
            team=self.team, submitted_by=self.student_b,
            title="Bob Task", link="https://docs.contrigrade.io/bob"
        )
        DeliverableContribution.objects.create(
            deliverable=d_bob, student=self.student_b,
            contribution_area="Bob Area", status='VERIFIED'
        )

        # Peer: Perfect 5/5 = 100.0%
        eval_ba = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_b, evaluatee=self.student_a)
        PeerEvaluationScore.objects.create(evaluation=eval_ba, criterion=self.criterion, score=5)

        self.client.force_login(self.instructor)
        resp = self.client.get(self.evidence_url)
        score_data = resp.context['score_data']

        # Ensure every component and total is capped at 100.0%
        self.assertEqual(score_data['github_score'], 100.0)
        self.assertEqual(score_data['deliverables_score'], 100.0)
        self.assertEqual(score_data['peer_score'], 100.0)
        self.assertEqual(score_data['final_score'], 100.0)
        self.assertEqual(score_data['pts_github'], 40.0)
        self.assertEqual(score_data['pts_deliverables'], 30.0)
        self.assertEqual(score_data['pts_peer'], 30.0)

        content = resp.content.decode('utf-8')
        self.assertIn("100.0%", content)
        self.assertIn("40.0 pts", content)
        self.assertIn("30.0 pts", content)

    # =========================================================================
    # TEST 4: Boundary Value - Zero-Weight Component Contributes 0 Points
    # =========================================================================
    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_boundary_zero_weight_component_yields_zero_points(self, mock_fetch, mock_analyze):
        """Boundary test: When a component weight is set to 0%, it contributes 0.0 pts to the final total."""
        # Reconfigure project weights: GitHub=0%, Deliverables=50%, Peer=50%
        self.project.weight_github = 0
        self.project.weight_deliverables = 50
        self.project.weight_peer = 50
        self.project.save()

        mock_fetch.return_value = {'status': 'success', 'commits': []}
        mock_analyze.return_value = self._mock_github_analytics(impact_a=10, impact_b=10)

        # 1 deliverable each -> 80.0%
        d1 = NonCodingDeliverable.objects.create(team=self.team, submitted_by=self.student_a, title="D1", link="https://a.com")
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_a, contribution_area="Doc", status='VERIFIED')
        d2 = NonCodingDeliverable.objects.create(team=self.team, submitted_by=self.student_b, title="D2", link="https://b.com")
        DeliverableContribution.objects.create(deliverable=d2, student=self.student_b, contribution_area="Doc", status='VERIFIED')

        # Peer 4/5 -> 80.0%
        eval_ba = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_b, evaluatee=self.student_a)
        PeerEvaluationScore.objects.create(evaluation=eval_ba, criterion=self.criterion, score=4)

        self.client.force_login(self.instructor)
        resp = self.client.get(self.evidence_url)
        score_data = resp.context['score_data']

        # GitHub points should be exactly 0.0 despite active code contributions
        self.assertEqual(score_data['pts_github'], 0.0)
        self.assertEqual(score_data['pts_deliverables'], 40.0)  # (80 * 50) / 100 = 40.0
        self.assertEqual(score_data['pts_peer'], 40.0)          # (80 * 50) / 100 = 40.0
        self.assertEqual(score_data['final_score'], 80.0)

        content = resp.content.decode('utf-8')
        self.assertIn("× 0%", content)
        self.assertIn("GitHub: 0.0 pts", content)

    # =========================================================================
    # TEST 5: Boundary Value - Weight Redistribution When Categories Are Missing
    # =========================================================================
    def test_boundary_missing_components_triggers_weight_redistribution(self):
        """Boundary test: When GitHub and deliverables are unavailable, weights redistribute dynamically."""
        # Unlink team GitHub repo so GitHub evidence is unavailable
        self.team.github_repo_url = None
        self.team.save()

        # No deliverables created in the team
        # Only Peer Evaluation exists: 4/5 = 80.0%
        eval_ba = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_b, evaluatee=self.student_a)
        PeerEvaluationScore.objects.create(evaluation=eval_ba, criterion=self.criterion, score=4)

        self.client.force_login(self.instructor)
        resp = self.client.get(self.evidence_url)
        score_data = resp.context['score_data']

        # Active weight sum is only 30% (< 100%), so redistribution is active
        self.assertTrue(score_data['is_redistributed'])
        self.assertIsNone(score_data['github_score'])
        self.assertIsNone(score_data['deliverables_score'])
        self.assertEqual(score_data['peer_score'], 80.0)
        self.assertEqual(score_data['pts_peer'], 80.0)  # (80.0 * 30) / 30 = 80.0
        self.assertEqual(score_data['final_score'], 80.0)

        content = resp.content.decode('utf-8')
        self.assertIn("Scaled up (missing category weight redistributed)", content)
        self.assertIn("GitHub not connected or evaluated.", content)
        self.assertIn("No verified non-coding tasks found.", content)

    # =========================================================================
    # TEST 6: Boundary Value - Total Absence of Evidence Displays Awaiting Notice
    # =========================================================================
    def test_boundary_zero_evidence_displays_awaiting_evidence_and_zero_total(self):
        """Boundary test: Zero evidence across the entire team displays 'Awaiting Evidence' and 0.0% total."""
        self.team.github_repo_url = None
        self.team.save()

        # No deliverables and no peer reviews created
        self.client.force_login(self.instructor)
        resp = self.client.get(self.evidence_url)
        score_data = resp.context['score_data']

        self.assertEqual(score_data['final_score'], 0.0)
        self.assertEqual(score_data['pts_github'], 0.0)
        self.assertEqual(score_data['pts_deliverables'], 0.0)
        self.assertEqual(score_data['pts_peer'], 0.0)
        self.assertIn("Awaiting Evidence", score_data['evidence_notes'])

        content = resp.content.decode('utf-8')
        self.assertIn("0.0%", content)
        self.assertIn("No peer evaluations received yet.", content)
        self.assertIn("No verified non-coding tasks found.", content)

    # =========================================================================
    # TEST 7: Evidence Display - Filters Unverified Claims and Keeps Anonymity
    # =========================================================================
    def test_evidence_display_filters_unverified_claims_and_preserves_anonymity(self):
        """Verifies that pending/rejected claims are excluded from score/display and peer reviews are anonymous."""
        self.team.github_repo_url = None
        self.team.save()

        deliv = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_a,
            title="UX Wireframes",
            link="https://figma.com/ux"
        )
        # Pending claim
        DeliverableContribution.objects.create(
            deliverable=deliv,
            student=self.student_a,
            contribution_area="Mobile Navigation Layout",
            status='PENDING'
        )
        # Rejected claim
        DeliverableContribution.objects.create(
            deliverable=deliv,
            student=self.student_b,
            contribution_area="Color Palette",
            status='REJECTED'
        )

        # Peer evaluation from Bob
        eval_ba = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_b, evaluatee=self.student_a)
        PeerEvaluationScore.objects.create(evaluation=eval_ba, criterion=self.criterion, score=5)

        self.client.force_login(self.instructor)
        resp = self.client.get(self.evidence_url)
        content = resp.content.decode('utf-8')

        # Pending & Rejected claims should NOT appear in verified deliverables
        self.assertNotIn("Mobile Navigation Layout", content)
        self.assertNotIn("Color Palette", content)

        # Peer review evidence should explicitly display anonymous reviewer label
        self.assertIn("From: Anonymous Teammate", content)
        self.assertIn("Technical Contribution", content)
        self.assertIn("5/5", content)
        self.assertNotIn(self.student_b.email, content)

    # =========================================================================
    # TEST 8: Boundary Value - Unequal Team Member Scoring Disparity
    # =========================================================================
    def test_boundary_relative_scoring_disparity_between_teammates(self):
        """Boundary test: Unequal deliverable count relative to team average separates member scores properly."""
        self.team.github_repo_url = None
        self.team.save()

        # Alice completed 2 tasks, Bob completed 0 tasks (team total=2, avg=1.0)
        d1 = NonCodingDeliverable.objects.create(team=self.team, submitted_by=self.student_a, title="T1", link="https://1.com")
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_a, contribution_area="T1 Area", status='VERIFIED')
        d2 = NonCodingDeliverable.objects.create(team=self.team, submitted_by=self.student_a, title="T2", link="https://2.com")
        DeliverableContribution.objects.create(deliverable=d2, student=self.student_a, contribution_area="T2 Area", status='VERIFIED')

        # Peer: both get 5/5
        eval_ba = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_b, evaluatee=self.student_a)
        PeerEvaluationScore.objects.create(evaluation=eval_ba, criterion=self.criterion, score=5)
        eval_ab = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_a, evaluatee=self.student_b)
        PeerEvaluationScore.objects.create(evaluation=eval_ab, criterion=self.criterion, score=5)

        # Alice's score check: (2 / 1.0) * 80 = 160% -> capped to 100.0%
        self.client.force_login(self.instructor)
        resp_a = self.client.get(self.evidence_url)
        self.assertEqual(resp_a.context['score_data']['deliverables_score'], 100.0)

        # Bob's score check: 0 tasks -> 0.0%
        bob_url = reverse('student_evidence_detail', kwargs={'team_id': self.team.pk, 'student_id': self.student_b.pk})
        resp_b = self.client.get(bob_url)
        self.assertEqual(resp_b.context['score_data']['deliverables_score'], 0.0)

    # =========================================================================
    # TEST 9: Boundary Value - Role-Based Access Control Boundaries
    # =========================================================================
    def test_boundary_role_based_access_control(self):
        """Boundary test: Only Instructors, Coordinators, and Admins can view evidence; Students are blocked."""
        # 1. Instructor -> Allowed (200)
        self.client.force_login(self.instructor)
        self.assertEqual(self.client.get(self.evidence_url).status_code, 200)

        # 2. Coordinator -> Allowed (200)
        self.client.force_login(self.coordinator)
        self.assertEqual(self.client.get(self.evidence_url).status_code, 200)

        # 3. Admin -> Allowed (200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.evidence_url).status_code, 200)

        # 4. Student -> Access Denied, redirect to student_dashboard (302)
        self.client.force_login(self.student_a)
        resp_student = self.client.get(self.evidence_url)
        self.assertEqual(resp_student.status_code, 302)
        self.assertIn(reverse('student_dashboard'), resp_student.url)

        # 5. Anonymous User -> Redirect to Login
        self.client.logout()
        resp_anon = self.client.get(self.evidence_url)
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn('/accounts/login/', resp_anon.url)

    # =========================================================================
    # TEST 10: Boundary Value - Invalid or Non-Team Student Handling
    # =========================================================================
    def test_boundary_invalid_or_non_team_student(self):
        """Boundary test: Non-existent student returns 404, student outside team redirects with error."""
        self.client.force_login(self.instructor)

        # Non-existent student ID -> 404
        invalid_student_url = reverse(
            'student_evidence_detail',
            kwargs={'team_id': self.team.pk, 'student_id': 999999}
        )
        self.assertEqual(self.client.get(invalid_student_url).status_code, 404)

        # Student exists but is not in this team -> Redirect to team_contribution_scores with error
        outsider_url = reverse(
            'student_evidence_detail',
            kwargs={'team_id': self.team.pk, 'student_id': self.outside_student.pk}
        )
        resp = self.client.get(outsider_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('team_contribution_scores', kwargs={'team_id': self.team.pk}), resp.url)
