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
class EvidenceAndScoreBreakdownIntegrationTests(TestCase):
    """
    Integration tests for contribution evidence and score breakdown.
    Acceptance criteria: Tests verify that saved evidence and calculated scores
    are correctly retrieved and linked to the right student and project.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Users
        self.instructor = User.objects.create_user(
            email="prof_integration@test.com",
            name="Prof. Donald Knuth",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.coordinator = User.objects.create_user(
            email="coord_integration@test.com",
            name="Coord Grace Hopper",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.student_alice = User.objects.create_user(
            email="alice_proj1@test.com",
            name="Alice Walker",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_alice.github_username = "alice_gh"
        self.student_alice.save()

        self.student_bob = User.objects.create_user(
            email="bob_proj1@test.com",
            name="Bob Smith",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob.github_username = "bob_gh"
        self.student_bob.save()

        self.student_charlie = User.objects.create_user(
            email="charlie_proj2@test.com",
            name="Charlie Brown",
            role=User.Role.STUDENT,
            password="password123"
        )

        # Academic structure
        self.course = Course.objects.create(
            course_code="CSE410",
            course_name="Advanced Software Design",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 1",
            instructor=self.instructor
        )
        self.section.students.add(self.student_alice, self.student_bob, self.student_charlie)

        # Project 1 (Distributed Backend)
        self.project_1 = Project.objects.create(
            section=self.section,
            title="Distributed Backend",
            deadline=timezone.now() + timedelta(days=14),
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        self.team_1 = Team.objects.create(
            project=self.project_1,
            team_name="Alpha Team",
            github_repo_url="https://github.com/contrigrade/alpha-backend"
        )
        TeamMember.objects.create(team=self.team_1, user=self.student_alice, role_in_team="Backend Lead")
        TeamMember.objects.create(team=self.team_1, user=self.student_bob, role_in_team="API Developer")

        self.crit_proj1 = EvaluationCriterion.objects.create(
            project=self.project_1,
            name="API & Architecture Quality",
            max_score=5
        )

        # Project 2 (Mobile Frontend)
        self.project_2 = Project.objects.create(
            section=self.section,
            title="Mobile Frontend",
            deadline=timezone.now() + timedelta(days=21),
            weight_github=30,
            weight_deliverables=40,
            weight_peer=30
        )
        self.team_2 = Team.objects.create(
            project=self.project_2,
            team_name="Mobile Squad"
        )
        TeamMember.objects.create(team=self.team_2, user=self.student_charlie, role_in_team="UI Lead")

        self.crit_proj2 = EvaluationCriterion.objects.create(
            project=self.project_2,
            name="Mobile Usability",
            max_score=5
        )

    # -------------------------------------------------------------------------
    # TEST 1: Saved evidence & scores linked strictly to right student and project
    # -------------------------------------------------------------------------
    def test_saved_evidence_and_scores_correctly_linked_to_student_and_project(self):
        """Verifies evidence and score breakdowns are isolated and linked to correct student & project."""
        # Evidence for Alice in Project 1
        deliv1 = NonCodingDeliverable.objects.create(
            team=self.team_1, submitted_by=self.student_alice,
            title="Project 1 Microservices Architecture", link="https://docs.p1.io"
        )
        DeliverableContribution.objects.create(
            deliverable=deliv1, student=self.student_alice,
            contribution_area="Service Discovery & gRPC", status='VERIFIED'
        )
        eval_bob_to_alice = PeerEvaluation.objects.create(
            team=self.team_1, evaluator=self.student_bob, evaluatee=self.student_alice
        )
        PeerEvaluationScore.objects.create(evaluation=eval_bob_to_alice, criterion=self.crit_proj1, score=5)

        # Evidence for Charlie in Project 2
        deliv2 = NonCodingDeliverable.objects.create(
            team=self.team_2, submitted_by=self.student_charlie,
            title="Project 2 Flutter Wireframes", link="https://figma.p2.io"
        )
        DeliverableContribution.objects.create(
            deliverable=deliv2, student=self.student_charlie,
            contribution_area="Cross-Platform Navigation", status='VERIFIED'
        )

        # View Alice's evidence detail in Project 1
        self.client.force_login(self.instructor)
        alice_url = reverse('student_evidence_detail', kwargs={'team_id': self.team_1.pk, 'student_id': self.student_alice.pk})
        resp = self.client.get(alice_url)
        self.assertEqual(resp.status_code, 200)

        # Alice sees only Project 1 data
        content = resp.content.decode('utf-8')
        self.assertIn("Project 1 Microservices Architecture", content)
        self.assertIn("Service Discovery &amp; gRPC", content)
        self.assertIn("API &amp; Architecture Quality", content)
        self.assertIn("5/5", content)

        # Charlie's Project 2 evidence is NOT leaked into Project 1 / Alice
        self.assertNotIn("Project 2 Flutter Wireframes", content)
        self.assertNotIn("Cross-Platform Navigation", content)
        self.assertNotIn("Mobile Usability", content)

    # -------------------------------------------------------------------------
    # TEST 2: Multi-team evidence isolation within the same project
    # -------------------------------------------------------------------------
    def test_multiteam_evidence_isolation_within_same_project(self):
        """Verifies two teams in same project have independent evidence and scoring metrics."""
        # Second team in Project 1
        team_beta = Team.objects.create(project=self.project_1, team_name="Beta Team")
        TeamMember.objects.create(team=team_beta, user=self.student_charlie, role_in_team="DB Admin")

        # Alpha Team: Alice has 2 verified tasks, Bob has 0
        d_alpha1 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_alice, title="Alpha Task 1", link="https://a1.io")
        DeliverableContribution.objects.create(deliverable=d_alpha1, student=self.student_alice, contribution_area="DB", status='VERIFIED')
        d_alpha2 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_alice, title="Alpha Task 2", link="https://a2.io")
        DeliverableContribution.objects.create(deliverable=d_alpha2, student=self.student_alice, contribution_area="Cache", status='VERIFIED')

        # Beta Team: Charlie has 1 verified task
        d_beta = NonCodingDeliverable.objects.create(team=team_beta, submitted_by=self.student_charlie, title="Beta Architecture", link="https://b.io")
        DeliverableContribution.objects.create(deliverable=d_beta, student=self.student_charlie, contribution_area="Beta Area", status='VERIFIED')

        # Calculate scores targeted at Alpha Team
        results_alpha = calculate_project_contribution_scores(self.project_1, target_team=self.team_1)
        members_alpha = {m['student_id']: m for m in results_alpha['master_data']}

        # Alpha Team average deliverable count = 2 / 2 = 1.0 (Charlie's task does NOT inflate team 1 count)
        self.assertEqual(members_alpha[self.student_alice.pk]['deliv_expected_count'], 1.0)
        self.assertEqual(members_alpha[self.student_alice.pk]['verified_deliverables'], 2)
        # Charlie is not in Alpha Team results
        self.assertNotIn(self.student_charlie.pk, members_alpha)

    # -------------------------------------------------------------------------
    # TEST 3: Multi-criteria and multiple deliverable evidence aggregation
    # -------------------------------------------------------------------------
    def test_evidence_aggregation_across_multiple_criteria_and_deliverables(self):
        """Verifies that multiple peer evaluation criteria and deliverables aggregate into score breakdown."""
        crit2 = EvaluationCriterion.objects.create(project=self.project_1, name="Team Collaboration", max_score=5)

        # Peer ratings: 4/5 on Architecture, 5/5 on Collaboration -> Total 9/10 = 90.0%
        eval_ba = PeerEvaluation.objects.create(team=self.team_1, evaluator=self.student_bob, evaluatee=self.student_alice)
        PeerEvaluationScore.objects.create(evaluation=eval_ba, criterion=self.crit_proj1, score=4)
        PeerEvaluationScore.objects.create(evaluation=eval_ba, criterion=crit2, score=5)

        # Two distinct deliverables
        d1 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_alice, title="API Schema", link="https://d1.io")
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_alice, contribution_area="Schema v1", status='VERIFIED')
        d2 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_alice, title="Deployment Topology", link="https://d2.io")
        DeliverableContribution.objects.create(deliverable=d2, student=self.student_alice, contribution_area="K8s Config", status='VERIFIED')

        self.client.force_login(self.instructor)
        alice_url = reverse('student_evidence_detail', kwargs={'team_id': self.team_1.pk, 'student_id': self.student_alice.pk})
        resp = self.client.get(alice_url)

        # Both criteria & deliverables retrieved in response context
        self.assertEqual(len(resp.context['deliverables']), 2)
        self.assertEqual(len(resp.context['peer_evals']), 2)
        self.assertEqual(resp.context['score_data']['peer_score'], 90.0)

        content = resp.content.decode('utf-8')
        self.assertIn("API &amp; Architecture Quality", content)
        self.assertIn("Team Collaboration", content)
        self.assertIn("API Schema", content)
        self.assertIn("Deployment Topology", content)

    # -------------------------------------------------------------------------
    # TEST 4: Live database persistence and verification update reflected in score
    # -------------------------------------------------------------------------
    def test_database_persistence_and_update_reflected_in_score_breakdown(self):
        """Verifies updating deliverable status in DB immediately updates calculated score breakdown."""
        self.team_1.github_repo_url = None
        self.team_1.save()

        # Start claim in PENDING status
        d = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_alice, title="Security Plan", link="https://sec.io")
        claim = DeliverableContribution.objects.create(
            deliverable=d, student=self.student_alice, contribution_area="Auth Flow", status='PENDING'
        )

        # PENDING claim means no verified deliverables yet
        results_before = calculate_project_contribution_scores(self.project_1, target_team=self.team_1)
        alice_before = next(m for m in results_before['master_data'] if m['student_id'] == self.student_alice.pk)
        self.assertIsNone(alice_before['deliverables_score'])

        # Instructor verifies claim in DB
        claim.status = 'VERIFIED'
        claim.save()

        # Recalculation retrieves verified status and computes score (1 task / 0.5 avg * 80 = 160% -> capped to 100%)
        results_after = calculate_project_contribution_scores(self.project_1, target_team=self.team_1)
        alice_after = next(m for m in results_after['master_data'] if m['student_id'] == self.student_alice.pk)
        self.assertEqual(alice_after['deliverables_score'], 100.0)
        self.assertEqual(alice_after['verified_deliverables'], 1)

    # -------------------------------------------------------------------------
    # TEST 5: Navigation flow from team scores to student evidence detail
    # -------------------------------------------------------------------------
    def test_navigation_flow_from_team_scores_to_student_evidence_detail(self):
        """Verifies team contribution score page links directly to student evidence detail view."""
        self.client.force_login(self.instructor)
        team_scores_url = reverse('team_contribution_scores', kwargs={'team_id': self.team_1.pk})
        resp_team = self.client.get(team_scores_url)
        self.assertEqual(resp_team.status_code, 200)

        # Evidence link is present in team scores page
        expected_evidence_url = reverse('student_evidence_detail', kwargs={'team_id': self.team_1.pk, 'student_id': self.student_alice.pk})
        self.assertIn(expected_evidence_url, resp_team.content.decode('utf-8'))

        # Follow link to evidence detail
        resp_evidence = self.client.get(expected_evidence_url)
        self.assertEqual(resp_evidence.status_code, 200)
        self.assertEqual(resp_evidence.context['student'].pk, self.student_alice.pk)
        self.assertEqual(resp_evidence.context['project'].pk, self.project_1.pk)

    # -------------------------------------------------------------------------
    # TEST 6: Student evidence retrieval with GitHub commits integration
    # -------------------------------------------------------------------------
    @patch('academic.utils.analyze_team_contributions')
    @patch('academic.utils.fetch_team_commits')
    def test_student_evidence_retrieval_with_github_commits_integration(self, mock_fetch, mock_analyze):
        """Verifies GitHub metrics are integrated into student evidence breakdown."""
        mock_fetch.return_value = {'status': 'success', 'commits': []}
        mock_analyze.return_value = {
            'total_commits': 8,
            'mapped_students': {
                self.student_alice.pk: {
                    'name': self.student_alice.name,
                    'github_username': 'alice_gh',
                    'commit_count': 6,
                    'total_additions': 250,
                    'total_deletions': 40,
                    'impact_score': 20,
                    'flags': []
                },
                self.student_bob.pk: {
                    'name': self.student_bob.name,
                    'github_username': 'bob_gh',
                    'commit_count': 2,
                    'total_additions': 50,
                    'total_deletions': 10,
                    'impact_score': 10,
                    'flags': []
                }
            }
        }

        self.client.force_login(self.instructor)
        alice_url = reverse('student_evidence_detail', kwargs={'team_id': self.team_1.pk, 'student_id': self.student_alice.pk})
        resp = self.client.get(alice_url)
        content = resp.content.decode('utf-8')

        # GitHub stats accurately linked to Alice
        self.assertEqual(resp.context['score_data']['commit_count'], 6)
        self.assertEqual(resp.context['score_data']['total_additions'], 250)
        self.assertEqual(resp.context['score_data']['total_deletions'], 40)
        self.assertIn("alice_gh", content)
        self.assertIn("+250", content)
        self.assertIn("-40", content)

