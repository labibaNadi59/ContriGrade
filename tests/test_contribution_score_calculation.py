import os
import sys
from datetime import timedelta
from unittest.mock import patch

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.test import TestCase, override_settings
from django.utils import timezone
from accounts.models import User
from academic.models import (
    Course, CourseSection, Project, Team, TeamMember,
    NonCodingDeliverable, DeliverableContribution,
    EvaluationCriterion, PeerEvaluation, PeerEvaluationScore
)
from academic.utils import calculate_project_contribution_scores


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ContributionScoreCalculationUnitTests(TestCase):
    """
    Unit tests for contribution score calculation.
    Acceptance criteria: Tests verify weighted calculations using different
    valid evidence and weight combinations.
    """

    def setUp(self):
        super().setUp()
        self.coordinator = User.objects.create_user(
            email="coord_calc@example.com",
            name="Coordinator Calc",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_calc@example.com",
            name="Instructor Calc",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE307",
            course_name="Algorithms",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 01",
            instructor=self.instructor
        )
        self.alice = User.objects.create_user(
            email="alice_calc@example.com",
            name="Alice",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.bob = User.objects.create_user(
            email="bob_calc@example.com",
            name="Bob",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.section.students.add(self.alice, self.bob)

        self.project = Project.objects.create(
            section=self.section,
            title="Calc Test Project",
            deadline=timezone.now() + timedelta(days=10),
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Calc Team",
            github_repo_url="https://github.com/testorg/calcrepo"
        )
        TeamMember.objects.create(team=self.team, user=self.alice)
        TeamMember.objects.create(team=self.team, user=self.bob)

        # Deliverables evidence: 2 verified deliverables for each student
        deliv = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.alice,
            title="Design Docs",
            link="https://docs.google.com/design"
        )
        DeliverableContribution.objects.create(deliverable=deliv, student=self.alice, contribution_area="DB", status='VERIFIED')
        DeliverableContribution.objects.create(deliverable=deliv, student=self.alice, contribution_area="API", status='VERIFIED')
        DeliverableContribution.objects.create(deliverable=deliv, student=self.bob, contribution_area="UI", status='VERIFIED')
        DeliverableContribution.objects.create(deliverable=deliv, student=self.bob, contribution_area="Tests", status='VERIFIED')

        # Peer evaluation evidence: criterion max_score 10
        crit = EvaluationCriterion.objects.create(project=self.project, name="Effort", max_score=10)
        eval_to_alice = PeerEvaluation.objects.create(team=self.team, evaluator=self.bob, evaluatee=self.alice)
        PeerEvaluationScore.objects.create(evaluation=eval_to_alice, criterion=crit, score=10)  # 100%

        eval_to_bob = PeerEvaluation.objects.create(team=self.team, evaluator=self.alice, evaluatee=self.bob)
        PeerEvaluationScore.objects.create(evaluation=eval_to_bob, criterion=crit, score=8)   # 80%

    def _mock_analytics(self, alice_impact=20, bob_impact=20):
        return {
            'total_commits': 10,
            'mapped_students': {
                self.alice.pk: {'commit_count': 5, 'impact_score': alice_impact, 'flags': []},
                self.bob.pk: {'commit_count': 5, 'impact_score': bob_impact, 'flags': []}
            }
        }

    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_01_balanced_weights_calculation(self, mock_fetch, mock_analyze):
        """Calculates correct weighted score with standard 40/30/30 weights."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        mock_analyze.return_value = self._mock_analytics(20, 20)

        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)

        # gh: (20/20)*80 = 80.0, deliv: (2/2)*80 = 80.0, peer: (10/10)*100 = 100.0
        # final: (80*40 + 80*30 + 100*30) / 100 = 86.0
        self.assertEqual(alice_data['github_score'], 80.0)
        self.assertEqual(alice_data['deliverables_score'], 80.0)
        self.assertEqual(alice_data['peer_score'], 100.0)
        self.assertEqual(alice_data['final_score'], 86.0)
        self.assertEqual(alice_data['pts_github'], 32.0)
        self.assertEqual(alice_data['pts_deliverables'], 24.0)
        self.assertEqual(alice_data['pts_peer'], 30.0)

    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_02_custom_weight_combination(self, mock_fetch, mock_analyze):
        """Calculates score correctly with custom 60/20/20 weights."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        mock_analyze.return_value = self._mock_analytics(20, 20)

        self.project.weight_github = 60
        self.project.weight_deliverables = 20
        self.project.weight_peer = 20
        self.project.save()

        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)

        # final: (80*60 + 80*20 + 100*20) / 100 = 84.0
        self.assertEqual(alice_data['final_score'], 84.0)
        self.assertEqual(alice_data['pts_github'], 48.0)
        self.assertEqual(alice_data['pts_deliverables'], 16.0)
        self.assertEqual(alice_data['pts_peer'], 20.0)

    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_03_zero_weight_component_excluded(self, mock_fetch, mock_analyze):
        """Zero weight component contributes 0 points and is excluded from weighting."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        mock_analyze.return_value = self._mock_analytics(20, 20)

        self.project.weight_github = 50
        self.project.weight_deliverables = 50
        self.project.weight_peer = 0
        self.project.save()

        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)

        # final: (80*50 + 80*50) / 100 = 80.0
        self.assertEqual(alice_data['final_score'], 80.0)
        self.assertEqual(alice_data['pts_peer'], 0.0)

    def test_04_missing_github_evidence_redistributes_weights(self):
        """Missing GitHub evidence dynamically redistributes weights between Deliverables and Peer."""
        self.team.github_repo_url = None
        self.team.save()

        # weights: 40/30/30, active sum = 60
        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)

        # final: (80*30 + 100*30) / 60 = 5400 / 60 = 90.0
        self.assertTrue(alice_data['is_redistributed'])
        self.assertIsNone(alice_data['github_score'])
        self.assertEqual(alice_data['final_score'], 90.0)

    def test_05_single_pillar_100_percent_weight(self):
        """100% assigned to a single pillar determines the total score."""
        self.team.github_repo_url = None
        self.team.save()

        self.project.weight_github = 0
        self.project.weight_deliverables = 100
        self.project.weight_peer = 0
        self.project.save()

        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)

        self.assertEqual(alice_data['final_score'], 80.0)
        self.assertEqual(alice_data['pts_deliverables'], 80.0)

    def test_06_edge_case_zero_evidence_yields_zero(self):
        """Student with no recorded evidence receives 0.0 score."""
        self.team.github_repo_url = None
        self.team.save()
        DeliverableContribution.objects.all().delete()
        PeerEvaluationScore.objects.all().delete()

        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)

        self.assertEqual(alice_data['final_score'], 0.0)
        self.assertIn("Awaiting Evidence", alice_data['evidence_notes'])
