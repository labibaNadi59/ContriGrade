
import csv
import io
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


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class FinalAssessmentReviewWorkflowIntegrationTests(TestCase):
    """
    Integration tests for the final assessment review workflow.
    Acceptance criteria: Tests verify that evidence, peer evaluations,
    anomaly flags, viva observations, and adjusted recommendations work together correctly.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        # 1. Users
        self.instructor = User.objects.create_user(
            email="inst_workflow@test.com",
            name="Prof. Alan Kay",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.coordinator = User.objects.create_user(
            email="coord_workflow@test.com",
            name="Coord Ada Lovelace",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.student_alice = User.objects.create_user(
            email="alice_workflow@test.com",
            name="Alice Smith",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_alice.github_username = "alice_dev"
        self.student_alice.save()

        self.student_bob = User.objects.create_user(
            email="bob_workflow@test.com",
            name="Bob Jones",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob.github_username = "bob_dev"
        self.student_bob.save()

        # 2. Academic Structure
        self.course = Course.objects.create(
            course_code="CSE495",
            course_name="Software Capstone Project",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student_alice, self.student_bob)

        # Configured weights: Deliverables 50%, Peer 50%, GitHub 0% by default
        self.project = Project.objects.create(
            section=self.section,
            title="Cloud Microservices Platform",
            deadline=timezone.now() + timedelta(days=14),
            weight_github=0,
            weight_deliverables=50,
            weight_peer=50
        )

        # Team Alpha
        self.team = Team.objects.create(
            project=self.project,
            team_name="Microservices Team",
            github_repo_url="https://github.com/capstone/microservices"
        )
        TeamMember.objects.create(team=self.team, user=self.student_alice, role_in_team="Backend Lead")
        TeamMember.objects.create(team=self.team, user=self.student_bob, role_in_team="Frontend Lead")

        # 3. Peer Evaluation Criteria
        self.crit_tech = EvaluationCriterion.objects.create(
            project=self.project,
            name="Technical Contribution",
            max_score=5
        )
        self.crit_collab = EvaluationCriterion.objects.create(
            project=self.project,
            name="Team Collaboration",
            max_score=5
        )

        # 4. Verified Deliverables (Evidence)
        d_alice = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_alice,
            title="API Architecture Specification",
            link="https://docs.alpha.io/api"
        )
        DeliverableContribution.objects.create(
            deliverable=d_alice,
            student=self.student_alice,
            contribution_area="gRPC & REST Endpoints",
            status='VERIFIED'
        )

        d_bob = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_bob,
            title="UI Wireframes & Component Specs",
            link="https://docs.alpha.io/ui"
        )
        DeliverableContribution.objects.create(
            deliverable=d_bob,
            student=self.student_bob,
            contribution_area="Design System",
            status='VERIFIED'
        )

        # 5. Peer Evaluation Scores
        # Bob evaluates Alice: 5/5 on tech, 5/5 on collab (10/10 -> 100%)
        eval_bob_to_alice = PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.student_bob,
            evaluatee=self.student_alice,
            general_feedback="Solid backend architecture and prompt communication."
        )
        PeerEvaluationScore.objects.create(evaluation=eval_bob_to_alice, criterion=self.crit_tech, score=5)
        PeerEvaluationScore.objects.create(evaluation=eval_bob_to_alice, criterion=self.crit_collab, score=5)

        # Alice evaluates Bob: 4/5 on tech, 4/5 on collab (8/10 -> 80%)
        eval_alice_to_bob = PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.student_alice,
            evaluatee=self.student_bob,
            general_feedback="Great UI designs and component organization."
        )
        PeerEvaluationScore.objects.create(evaluation=eval_alice_to_bob, criterion=self.crit_tech, score=4)
        PeerEvaluationScore.objects.create(evaluation=eval_alice_to_bob, criterion=self.crit_collab, score=4)

        # URLs
        self.alice_detail_url = reverse('student_evidence_detail', kwargs={
            'team_id': self.team.pk,
            'student_id': self.student_alice.user_id
        })
        self.bob_detail_url = reverse('student_evidence_detail', kwargs={
            'team_id': self.team.pk,
            'student_id': self.student_bob.user_id
        })
        self.team_scores_url = reverse('team_contribution_scores', kwargs={'team_id': self.team.pk})
        self.team_report_url = reverse('team_assessment_report', kwargs={'team_id': self.team.pk})

        self.client.force_login(self.instructor)

    # -------------------------------------------------------------------------
    # TEST 1: Evidence & Peer Evaluation Synthesis
    # -------------------------------------------------------------------------
    def test_01_evidence_and_peer_evaluation_synthesis(self):
        """Verifies multi-pillar evidence and peer evaluations synthesize into weighted recommended scores."""
        response = self.client.get(self.alice_detail_url)
        self.assertEqual(response.status_code, 200)

        score_data = response.context['score_data']
        # Deliverables: 1 task / 1.0 expected avg * 80 = 80.0%
        self.assertEqual(score_data['deliverables_score'], 80.0)
        # Peer: 10 / 10 max * 100 = 100.0%
        self.assertEqual(score_data['peer_score'], 100.0)
        # Weighted points: (80.0 * 50) / 100 = 40.0 pts; (100.0 * 50) / 100 = 50.0 pts
        self.assertEqual(score_data['pts_deliverables'], 40.0)
        self.assertEqual(score_data['pts_peer'], 50.0)
        # Recommended score: 40.0 + 50.0 = 90.0%
        self.assertEqual(score_data['final_score'], 90.0)

        # Verify evidence detail template renders both pillars
        content = response.content.decode('utf-8')
        self.assertIn("API Architecture Specification", content)
        self.assertIn("gRPC &amp; REST Endpoints", content)
        self.assertIn("Technical Contribution", content)
        self.assertIn("Team Collaboration", content)
        self.assertIn("90.0%", content)

    # -------------------------------------------------------------------------
    # TEST 2: Anomaly Flags Trigger Viva Defense Prompt
    # -------------------------------------------------------------------------
    @patch('academic.utils.fetch_team_commits')
    def test_02_anomaly_flags_trigger_viva_defense_prompt(self, mock_fetch):
        """Verifies commit anomalies trigger integrity flags alerting the instructor for viva verification."""
        # Enable GitHub weight and mock a massive code dump commit (>1000 additions)
        self.project.weight_github = 40
        self.project.weight_deliverables = 30
        self.project.weight_peer = 30
        self.project.save()

        mock_fetch.return_value = {
            'status': 'success',
            'commits': [
                {
                    'sha': 'dump123456',
                    'author_username': 'alice_dev',
                    'date': '2026-10-20T14:00:00Z',
                    'additions': 1600,
                    'deletions': 10,
                    'message': 'Initial codebase dump',
                    'is_merge': False
                }
            ]
        }

        response = self.client.get(self.alice_detail_url)
        self.assertEqual(response.status_code, 200)

        score_data = response.context['score_data']
        # Verify integrity flags engine detected the massive commit dump
        self.assertTrue(len(score_data['flags']) > 0)
        self.assertTrue(any("massive code dumps" in f for f in score_data['flags']))
        self.assertEqual(score_data['total_additions'], 1600)

    # -------------------------------------------------------------------------
    # TEST 3: Viva Observations and Score Adjustment Override
    # -------------------------------------------------------------------------
    def test_03_viva_observations_and_score_adjustment_override(self):
        """Verifies viva observations and score adjustments override the recommended baseline."""
        viva_notes = "Investigated task distribution during oral viva; verified student authored core microservice."
        adj_reason = "Demonstrated outstanding architectural defense in viva."
        adjusted_score = 95.0

        # Instructor saves viva assessment without final approval (draft mode)
        response = self.client.post(self.alice_detail_url, {
            'action': 'save_assessment',
            'viva_observations': viva_notes,
            'adjusted_score': str(adjusted_score),
            'adjustment_reason': adj_reason
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, self.alice_detail_url)

        # Verify database record
        fa = FinalAssessment.objects.get(project=self.project, student=self.student_alice)
        self.assertEqual(fa.recommended_score, 90.0)
        self.assertEqual(fa.adjusted_score, adjusted_score)
        self.assertEqual(fa.viva_observations, viva_notes)
        self.assertEqual(fa.adjustment_reason, adj_reason)
        self.assertFalse(fa.is_approved)
        self.assertEqual(fa.updated_by, self.instructor)

        # Verify UI renders adjusted score and preserves recommended score strike-through
        view_resp = self.client.get(self.alice_detail_url)
        self.assertEqual(view_resp.status_code, 200)
        self.assertEqual(view_resp.context['assessment'], fa)
        content = view_resp.content.decode('utf-8')
        self.assertIn("95.0%", content)
        self.assertIn("90.0%", content)
        self.assertIn(viva_notes, content)

    # -------------------------------------------------------------------------
    # TEST 4: Save and Approve Assessment Audit Trail
    # -------------------------------------------------------------------------
    def test_04_save_and_approve_assessment_audit_trail(self):
        """Verifies 'save_and_approve' activates official approval state with complete audit metadata."""
        viva_notes = "Exceptional oral defense and deep concurrency knowledge."
        adj_reason = "Comprehensive defense beyond baseline requirements."

        # 1. Save and approve
        post_resp = self.client.post(self.alice_detail_url, {
            'action': 'save_and_approve',
            'viva_observations': viva_notes,
            'adjusted_score': '96.0',
            'adjustment_reason': adj_reason
        })
        self.assertEqual(post_resp.status_code, 302)

        fa = FinalAssessment.objects.get(project=self.project, student=self.student_alice)
        self.assertTrue(fa.is_approved)
        self.assertEqual(fa.approved_by, self.instructor)
        self.assertIsNotNone(fa.approved_at)
        self.assertEqual(fa.adjusted_score, 96.0)

        # 2. Verify approved state in UI
        get_resp = self.client.get(self.alice_detail_url)
        content = get_resp.content.decode('utf-8')
        self.assertIn("Approved", content)

        # 3. Unlock approval via 'unapprove_score'
        unlock_resp = self.client.post(self.alice_detail_url, {
            'action': 'unapprove_score',
            'viva_observations': viva_notes,
            'adjusted_score': '96.0',
            'adjustment_reason': adj_reason
        })
        self.assertEqual(unlock_resp.status_code, 302)

        fa.refresh_from_db()
        self.assertFalse(fa.is_approved)
        self.assertIsNone(fa.approved_by)
        self.assertIsNone(fa.approved_at)

    # -------------------------------------------------------------------------
    # TEST 5: Revert Score Adjustment to Recommended Baseline
    # -------------------------------------------------------------------------
    def test_05_revert_score_adjustment_to_recommended_baseline(self):
        """Verifies resetting score reverts to recommended baseline while preserving viva observations."""
        # Setup existing adjusted assessment
        FinalAssessment.objects.create(
            project=self.project,
            team=self.team,
            student=self.student_alice,
            recommended_score=90.0,
            adjusted_score=98.0,
            adjustment_reason="Temporary viva boost",
            viva_observations="Student explained architecture clearly during oral exam.",
            is_approved=False,
            updated_by=self.instructor
        )

        # Instructor decides to reset to recommended baseline
        reset_resp = self.client.post(self.alice_detail_url, {
            'action': 'reset_score',
            'viva_observations': "Student explained architecture clearly during oral exam.",
        })
        self.assertEqual(reset_resp.status_code, 302)

        fa = FinalAssessment.objects.get(project=self.project, student=self.student_alice)
        self.assertIsNone(fa.adjusted_score)
        self.assertEqual(fa.adjustment_reason, '')
        # Viva observations must remain preserved
        self.assertEqual(fa.viva_observations, "Student explained architecture clearly during oral exam.")

        # In UI, the recommended score (90.0%) is restored as the active final score
        view_resp = self.client.get(self.alice_detail_url)
        self.assertIsNone(view_resp.context['assessment'].adjusted_score)
        self.assertEqual(view_resp.context['score_data']['final_score'], 90.0)

    # -------------------------------------------------------------------------
    # TEST 6: End-to-End Assessment Workflow to Reports
    # -------------------------------------------------------------------------
    def test_06_end_to_end_assessment_workflow_to_reports(self):
        """Verifies evidence, peer evals, viva notes, and adjustments flow end-to-end to team views and reports."""
        # Alice: Adjusted to 94.0%, viva recorded, approved
        FinalAssessment.objects.create(
            project=self.project,
            team=self.team,
            student=self.student_alice,
            recommended_score=90.0,
            adjusted_score=94.0,
            adjustment_reason="Superb technical viva defense",
            viva_observations="Defended microservices architecture with precision.",
            is_approved=True,
            approved_by=self.instructor,
            approved_at=timezone.now(),
            updated_by=self.instructor
        )

        # Bob: Recommended baseline (80.0%), viva recorded, approved
        FinalAssessment.objects.create(
            project=self.project,
            team=self.team,
            student=self.student_bob,
            recommended_score=80.0,
            adjusted_score=None,
            adjustment_reason="",
            viva_observations="Satisfactory explanation of design system.",
            is_approved=True,
            approved_by=self.instructor,
            approved_at=timezone.now(),
            updated_by=self.instructor
        )

        # Part A: Team Contribution Scores View Integration
        resp_team = self.client.get(self.team_scores_url)
        self.assertEqual(resp_team.status_code, 200)
        self.assertTrue(resp_team.context['all_approved'])
        self.assertEqual(resp_team.context['approved_count'], 2)
        # Average of Alice's adjusted (94.0) and Bob's recommended (80.0) = 87.0%
        self.assertEqual(resp_team.context['team_avg_score'], 87.0)

        # Part B: Official Team Assessment Report HTML
        resp_report = self.client.get(self.team_report_url)
        self.assertEqual(resp_report.status_code, 200)
        report_html = resp_report.content.decode('utf-8')
        self.assertIn("94.0%", report_html)
        self.assertIn("80.0%", report_html)
        self.assertIn("Defended microservices architecture with precision.", report_html)
        self.assertIn("Superb technical viva defense", report_html)

        # Part C: Official Team Assessment Report CSV Export
        resp_csv = self.client.get(f"{self.team_report_url}?export=csv")
        self.assertEqual(resp_csv.status_code, 200)
        self.assertEqual(resp_csv['Content-Type'], 'text/csv')

        reader = list(csv.reader(io.StringIO(resp_csv.content.decode('utf-8'))))
        header = reader[0]
        self.assertIn('Student Name', header)
        self.assertIn('Final Official Score (%)', header)
        self.assertIn('Viva Observations', header)

        alice_row = next(r for r in reader[1:] if r[0] == 'Alice Smith')
        self.assertEqual(alice_row[8], '94.0')  # Final Official Score
        self.assertEqual(alice_row[9], 'Approved')
        self.assertEqual(alice_row[10], 'Prof. Alan Kay')
        self.assertEqual(alice_row[12], 'Defended microservices architecture with precision.')
        self.assertEqual(alice_row[13], 'Superb technical viva defense')

        bob_row = next(r for r in reader[1:] if r[0] == 'Bob Jones')
        self.assertEqual(bob_row[8], '80.0')  # Final Official Score (recommended baseline)
        self.assertEqual(bob_row[9], 'Approved')
        self.assertEqual(bob_row[12], 'Satisfactory explanation of design system.')

