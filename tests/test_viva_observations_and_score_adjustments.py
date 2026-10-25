
import os
import sys
from datetime import timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.messages import get_messages

from accounts.models import User
from academic.models import (
    Course, CourseSection, Project, Team, TeamMember,
    NonCodingDeliverable, DeliverableContribution, FinalAssessment
)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class VivaObservationsAndScoreAdjustmentsUnitTests(TestCase):
    """
    Unit tests for viva observations and score adjustments.
    Acceptance criteria: Tests verify observation saving, score adjustments,
    validation, and data persistence across 6 concise test cases.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Users
        self.instructor = User.objects.create_user(
            email="inst_viva@test.com",
            name="Prof. Donald Knuth",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.coordinator = User.objects.create_user(
            email="coord_viva@test.com",
            name="Coord Grace Hopper",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.student = User.objects.create_user(
            email="student_viva@test.com",
            name="Alice Smith",
            role=User.Role.STUDENT,
            password="password123"
        )

        # Academic structure
        self.course = Course.objects.create(
            course_code="CSE480",
            course_name="Software Architecture",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 1",
            instructor=self.instructor
        )
        self.section.students.add(self.student)

        self.project = Project.objects.create(
            section=self.section,
            title="Distributed Cloud Platform",
            deadline=timezone.now() + timedelta(days=14),
            weight_github=0,
            weight_deliverables=100,
            weight_peer=0
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Cloud Team"
        )
        TeamMember.objects.create(
            team=self.team,
            user=self.student,
            role_in_team="Backend Lead"
        )

        # Verified deliverable so student has a recommended score
        deliv = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student,
            title="System Architecture Document",
            link="https://docs.cloud.io/arch"
        )
        DeliverableContribution.objects.create(
            deliverable=deliv,
            student=self.student,
            contribution_area="API & Architecture",
            status='VERIFIED'
        )

        self.url = reverse('student_evidence_detail', kwargs={
            'team_id': self.team.pk,
            'student_id': self.student.user_id
        })
        self.client.force_login(self.instructor)

    # -------------------------------------------------------------------------
    # TEST 1: Observation Saving
    # -------------------------------------------------------------------------
    def test_01_save_viva_observations_successfully(self):
        """Verifies saving viva defense observations records the text on FinalAssessment."""
        viva_text = "Demonstrated deep understanding of microservices and answered anomaly questions clearly."
        response = self.client.post(self.url, {
            'viva_observations': viva_text,
            'adjusted_score': '',
            'adjustment_reason': '',
        })

        self.assertEqual(response.status_code, 302)
        assessment = FinalAssessment.objects.get(project=self.project, student=self.student)
        self.assertEqual(assessment.viva_observations, viva_text)
        self.assertEqual(assessment.updated_by, self.instructor)
        self.assertEqual(assessment.recommended_score, 80.0)
        self.assertIsNone(assessment.adjusted_score)
        self.assertEqual(assessment.effective_final_score, 80.0)

    # -------------------------------------------------------------------------
    # TEST 2: Score Adjustment with Reason
    # -------------------------------------------------------------------------
    def test_02_score_adjustment_with_reason(self):
        """Verifies applying a score adjustment records the adjusted score, reason, and updates effective score."""
        response = self.client.post(self.url, {
            'viva_observations': "Defense answers were exceptional.",
            'adjusted_score': '88.5',
            'adjustment_reason': "Demonstrated exceptional mastery during viva examination.",
        })

        self.assertEqual(response.status_code, 302)
        assessment = FinalAssessment.objects.get(project=self.project, student=self.student)
        self.assertEqual(assessment.adjusted_score, 88.5)
        self.assertEqual(assessment.adjustment_reason, "Demonstrated exceptional mastery during viva examination.")
        self.assertEqual(assessment.effective_final_score, 88.5)

    # -------------------------------------------------------------------------
    # TEST 3: Reset Score Adjustment to Recommended
    # -------------------------------------------------------------------------
    def test_03_reset_score_adjustment_to_recommended(self):
        """Verifies resetting score clears the adjustment and reverts effective score to recommended score."""
        FinalAssessment.objects.create(
            project=self.project,
            team=self.team,
            student=self.student,
            recommended_score=80.0,
            adjusted_score=92.0,
            adjustment_reason="Prior viva bonus",
            viva_observations="Solid defense."
        )

        response = self.client.post(self.url, {
            'action': 'reset_score',
            'viva_observations': "Solid defense.",
        })

        self.assertEqual(response.status_code, 302)
        assessment = FinalAssessment.objects.get(project=self.project, student=self.student)
        self.assertIsNone(assessment.adjusted_score)
        self.assertEqual(assessment.adjustment_reason, "")
        self.assertEqual(assessment.effective_final_score, 80.0)
        self.assertEqual(assessment.viva_observations, "Solid defense.")

    # -------------------------------------------------------------------------
    # TEST 4: Score Validation (Bounds & Formats)
    # -------------------------------------------------------------------------
    def test_04_adjusted_score_validation(self):
        """Verifies validation rejects scores > 100, negative scores, and non-numeric formats."""
        # Case A: Score above 100
        resp_high = self.client.post(self.url, {
            'adjusted_score': '105.0',
            'viva_observations': 'Out of bounds high'
        })
        self.assertEqual(resp_high.status_code, 302)
        messages_high = [m.message for m in get_messages(resp_high.wsgi_request)]
        self.assertIn("Adjusted score must be between 0 and 100.", messages_high)

        # Case B: Negative score
        resp_neg = self.client.post(self.url, {
            'adjusted_score': '-5.0',
            'viva_observations': 'Out of bounds negative'
        })
        self.assertEqual(resp_neg.status_code, 302)
        messages_neg = [m.message for m in get_messages(resp_neg.wsgi_request)]
        self.assertIn("Adjusted score must be between 0 and 100.", messages_neg)

        # Case C: Invalid non-numeric string
        resp_invalid = self.client.post(self.url, {
            'adjusted_score': 'eighty_five',
            'viva_observations': 'Non numeric'
        })
        self.assertEqual(resp_invalid.status_code, 302)
        messages_invalid = [m.message for m in get_messages(resp_invalid.wsgi_request)]
        self.assertIn("Invalid score format entered.", messages_invalid)

        # Verify no invalid record was saved
        self.assertFalse(FinalAssessment.objects.filter(project=self.project, student=self.student).exists())

    # -------------------------------------------------------------------------
    # TEST 5: Data Persistence & Update In-Place
    # -------------------------------------------------------------------------
    def test_05_data_persistence_and_update_in_place(self):
        """Verifies observation and score updates persist in place without duplicate records."""
        # Initial save
        self.client.post(self.url, {
            'viva_observations': "Initial viva round 1 notes.",
            'adjusted_score': '',
            'adjustment_reason': '',
        })
        self.assertEqual(FinalAssessment.objects.filter(project=self.project, student=self.student).count(), 1)

        # Subsequent update
        self.client.post(self.url, {
            'viva_observations': "Updated viva round 2 notes with code review.",
            'adjusted_score': '84.0',
            'adjustment_reason': "Demonstrated code clarity during live viva walkthrough.",
        })

        # Ensure single record persisted with updated values
        self.assertEqual(FinalAssessment.objects.filter(project=self.project, student=self.student).count(), 1)
        assessment = FinalAssessment.objects.get(project=self.project, student=self.student)
        self.assertEqual(assessment.viva_observations, "Updated viva round 2 notes with code review.")
        self.assertEqual(assessment.adjusted_score, 84.0)
        self.assertEqual(assessment.adjustment_reason, "Demonstrated code clarity during live viva walkthrough.")
        self.assertEqual(assessment.effective_final_score, 84.0)

    # -------------------------------------------------------------------------
    # TEST 6: Approval Workflow & Metadata Persistence
    # -------------------------------------------------------------------------
    def test_06_approval_and_unapproval_workflow_persistence(self):
        """Verifies approving and unlocking assessments persists approval flags, timestamps, and reviewers."""
        # Save and approve
        self.client.post(self.url, {
            'action': 'save_and_approve',
            'viva_observations': "Approved viva defense.",
            'adjusted_score': '90.0',
            'adjustment_reason': "Outstanding viva response.",
        })

        assessment = FinalAssessment.objects.get(project=self.project, student=self.student)
        self.assertTrue(assessment.is_approved)
        self.assertEqual(assessment.approved_by, self.instructor)
        self.assertIsNotNone(assessment.approved_at)
        self.assertEqual(assessment.effective_final_score, 90.0)

        # Unlock / unapprove
        self.client.post(self.url, {
            'action': 'unapprove_score',
            'viva_observations': "Approved viva defense.",
            'adjusted_score': '90.0',
        })

        assessment.refresh_from_db()
        self.assertFalse(assessment.is_approved)
        self.assertIsNone(assessment.approved_by)
        self.assertIsNone(assessment.approved_at)
        # Observations and score remain preserved while unlocked
        self.assertEqual(assessment.viva_observations, "Approved viva defense.")
        self.assertEqual(assessment.adjusted_score, 90.0)

