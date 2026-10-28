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
    EvaluationCriterion, PeerEvaluation, PeerEvaluationScore,
    FinalAssessment
)
from academic.utils import calculate_project_contribution_scores


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CompleteContributionScoreCalculationWorkflowIntegrationTests(TestCase):
    """
    Integration tests for complete contribution score calculation workflow.
    Acceptance criteria: GitHub, non-coding, and peer evidence are combined
    with configured weights and a correct individual score recommendation is produced.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_workflow_calc@example.com",
            name="Coordinator Workflow",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_workflow_calc@example.com",
            name="Instructor Workflow",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE308",
            course_name="Compiler Design",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 01",
            instructor=self.instructor
        )
        self.alice = User.objects.create_user(
            email="alice_wf@example.com",
            name="Alice Walker",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.bob = User.objects.create_user(
            email="bob_wf@example.com",
            name="Bob Builder",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.section.students.add(self.alice, self.bob)

        self.deadline = timezone.now() + timedelta(days=15)
        self.project = Project.objects.create(
            section=self.section,
            title="Compiler Project",
            deadline=self.deadline,
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Lexers",
            github_repo_url="https://github.com/testorg/compiler"
        )
        TeamMember.objects.create(team=self.team, user=self.alice)
        TeamMember.objects.create(team=self.team, user=self.bob)

        # Non-coding deliverable evidence
        deliv = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.alice,
            title="Grammar Specification",
            link="https://docs.example.com/grammar"
        )
        DeliverableContribution.objects.create(deliverable=deliv, student=self.alice, contribution_area="Grammar", status='VERIFIED')
        DeliverableContribution.objects.create(deliverable=deliv, student=self.bob, contribution_area="Parser", status='VERIFIED')

        # Peer evaluation evidence
        crit = EvaluationCriterion.objects.create(project=self.project, name="Contribution", max_score=10)
        eval_alice = PeerEvaluation.objects.create(team=self.team, evaluator=self.bob, evaluatee=self.alice)
        PeerEvaluationScore.objects.create(evaluation=eval_alice, criterion=crit, score=10)
        eval_bob = PeerEvaluation.objects.create(team=self.team, evaluator=self.alice, evaluatee=self.bob)
        PeerEvaluationScore.objects.create(evaluation=eval_bob, criterion=crit, score=8)

    def _mock_analytics(self, alice_impact=20, bob_impact=20):
        return {
            'total_commits': 10,
            'mapped_students': {
                self.alice.pk: {'commit_count': 6, 'impact_score': alice_impact, 'flags': []},
                self.bob.pk: {'commit_count': 4, 'impact_score': bob_impact, 'flags': []}
            }
        }

    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_01_complete_three_pillar_calculation_workflow(self, mock_fetch, mock_analyze):
        """GitHub, non-coding, and peer evidence are combined to produce score recommendation."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        mock_analyze.return_value = self._mock_analytics(20, 20)

        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)

        # gh: 80.0 (40%), deliv: 80.0 (30%), peer: 100.0 (30%) -> final: 86.0
        self.assertEqual(alice_data['github_score'], 80.0)
        self.assertEqual(alice_data['deliverables_score'], 80.0)
        self.assertEqual(alice_data['peer_score'], 100.0)
        self.assertEqual(alice_data['final_score'], 86.0)

    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_02_individual_score_differentiation(self, mock_fetch, mock_analyze):
        """Different evidence levels produce distinct individual score recommendations."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        # Alice higher impact (30) than Bob (10)
        mock_analyze.return_value = self._mock_analytics(alice_impact=30, bob_impact=10)

        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)
        bob_data = next(s for s in results['master_data'] if s['student_id'] == self.bob.pk)

        self.assertGreater(alice_data['github_score'], bob_data['github_score'])
        self.assertGreater(alice_data['final_score'], bob_data['final_score'])

    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_03_weight_reconfiguration_updates_recommendation(self, mock_fetch, mock_analyze):
        """Updating project weights through edit project workflow recalculates score recommendations."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        mock_analyze.return_value = self._mock_analytics(20, 20)

        self.client.force_login(self.instructor)
        # Update weights to 60/20/20 via HTTP workflow
        self.client.post(reverse('edit_project', kwargs={'project_id': self.project.pk}), {
            'update_project': '1',
            'title': self.project.title,
            'description': self.project.description,
            'section': self.section.pk,
            'deadline': self.deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 60,
            'weight_deliverables': 20,
            'weight_peer': 20
        })

        self.project.refresh_from_db()
        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)

        # With 60/20/20: (80*60 + 80*20 + 100*20)/100 = 84.0
        self.assertEqual(alice_data['final_score'], 84.0)
        self.assertEqual(alice_data['pts_github'], 48.0)

    def test_04_missing_pillar_workflow_handling(self):
        """Workflow calculates valid score recommendation when repository is absent."""
        self.team.github_repo_url = None
        self.team.save()

        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)

        self.assertTrue(alice_data['is_redistributed'])
        self.assertIsNone(alice_data['github_score'])
        self.assertEqual(alice_data['final_score'], 90.0)

    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_05_final_assessment_persistence_workflow(self, mock_fetch, mock_analyze):
        """Calculated recommended score is persisted into FinalAssessment model."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        mock_analyze.return_value = self._mock_analytics(20, 20)

        results = calculate_project_contribution_scores(self.project)
        alice_data = next(s for s in results['master_data'] if s['student_id'] == self.alice.pk)

        assessment = FinalAssessment.objects.create(
            project=self.project,
            team=self.team,
            student=self.alice,
            recommended_score=alice_data['final_score'],
            updated_by=self.instructor
        )
        self.assertEqual(assessment.recommended_score, 86.0)
        self.assertEqual(assessment.effective_final_score, 86.0)

    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_06_team_contribution_scores_view_integration(self, mock_fetch, mock_analyze):
        """Instructor visits team contribution scores view and views recommended scores."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        mock_analyze.return_value = self._mock_analytics(20, 20)

        self.client.force_login(self.instructor)
        url = reverse('team_contribution_scores', kwargs={'team_id': self.team.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertIn(self.alice.name, content)
        self.assertIn(self.bob.name, content)
