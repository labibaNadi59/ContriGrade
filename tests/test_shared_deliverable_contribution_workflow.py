import os
import sys
import unittest
from datetime import timedelta

import django
from django.test import TestCase, Client
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from django.contrib.messages import get_messages

from accounts.models import User
from academic.models import (
    Course, CourseSection, Project, Team, TeamMember,
    NonCodingDeliverable, DeliverableContribution
)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# =====================================================================
# 1. MODEL UNIT TESTS (DeliverableContribution)
# =====================================================================
class DeliverableContributionModelTests(TestCase):
    """Unit tests for the DeliverableContribution model."""

    def setUp(self):
        self.coordinator = User.objects.create_user(
            email="coord_contrib_m@test.com",
            name="Coordinator Test",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_contrib_m@test.com",
            name="Instructor Test",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_submitter = User.objects.create_user(
            email="submitter_contrib_m@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_contributor = User.objects.create_user(
            email="contributor_contrib_m@test.com",
            name="Bob Contributor",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student_submitter, self.student_contributor)

        self.project = Project.objects.create(
            section=self.section,
            title="Shared Project",
            description="Testing shared contributions",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Beta Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student_submitter)
        TeamMember.objects.create(team=self.team, user=self.student_contributor)

        self.deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_submitter,
            title="Software Architecture Document",
            link="https://docs.google.com/document/d/architecture-xyz",
            description="Overall architecture and system components"
        )

    def test_create_contribution_success(self):
        """Test creating a DeliverableContribution with default status PENDING."""
        contrib = DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student_contributor,
            contribution_area="Designed the database ERD & schemas"
        )
        self.assertIsNotNone(contrib.pk)
        self.assertEqual(contrib.deliverable, self.deliverable)
        self.assertEqual(contrib.student, self.student_contributor)
        self.assertEqual(contrib.contribution_area, "Designed the database ERD & schemas")
        self.assertEqual(contrib.status, "PENDING")
        self.assertIsNotNone(contrib.created_at)

    def test_contribution_str_representation(self):
        """Test __str__ representation includes student name, area, and status."""
        contrib = DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student_contributor,
            contribution_area="Created UI Wireframes",
            status="PENDING"
        )
        self.assertEqual(str(contrib), "Bob Contributor - Created UI Wireframes (Pending Verification)")

        contrib.status = "VERIFIED"
        contrib.save()
        self.assertEqual(str(contrib), "Bob Contributor - Created UI Wireframes (Verified)")

        contrib.status = "REJECTED"
        contrib.save()
        self.assertEqual(str(contrib), "Bob Contributor - Created UI Wireframes (Rejected)")

    def test_status_choices_valid(self):
        """Test all valid STATUS_CHOICES values."""
        for status_val in ['PENDING', 'VERIFIED', 'REJECTED']:
            contrib = DeliverableContribution.objects.create(
                deliverable=self.deliverable,
                student=self.student_contributor,
                contribution_area=f"Task {status_val}",
                status=status_val
            )
            self.assertEqual(contrib.status, status_val)

    def test_cascade_delete_deliverable(self):
        """Deleting the deliverable cascades to delete all linked contributions."""
        DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student_contributor,
            contribution_area="Auth API Spec"
        )
        self.assertEqual(DeliverableContribution.objects.filter(deliverable=self.deliverable).count(), 1)
        self.deliverable.delete()
        self.assertEqual(DeliverableContribution.objects.count(), 0)

    def test_cascade_delete_student(self):
        """Deleting the student cascades to delete their contributions."""
        contrib = DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student_contributor,
            contribution_area="Auth API Spec"
        )
        self.student_contributor.delete()
        self.assertFalse(DeliverableContribution.objects.filter(pk=contrib.pk).exists())

    def test_multiple_contributions_for_same_deliverable(self):
        """A deliverable can have multiple contribution claims from different team members."""
        student_extra = User.objects.create_user(
            email="extra_contrib_m@test.com",
            name="Charlie Contributor",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.section.students.add(student_extra)
        TeamMember.objects.create(team=self.team, user=student_extra)

        DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student_contributor,
            contribution_area="Database Modeling"
        )
        DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=student_extra,
            contribution_area="Frontend Component Architecture"
        )
        self.assertEqual(self.deliverable.contributions.count(), 2)


# =====================================================================
# 2. SUBMISSION & TAGGING WORKFLOW TESTS (student_team_progress)
# =====================================================================
class DeliverableTaggingWorkflowTests(TestCase):
    """Tests for tagging teammates during deliverable submission."""

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_tag@test.com",
            name="Coordinator Tag",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_tag@test.com",
            name="Instructor Tag",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_submitter = User.objects.create_user(
            email="alice_tag@test.com",
            name="Alice Tag",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_teammate1 = User.objects.create_user(
            email="bob_tag@test.com",
            name="Bob Tag",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_teammate2 = User.objects.create_user(
            email="charlie_tag@test.com",
            name="Charlie Tag",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_outsider = User.objects.create_user(
            email="outsider_tag@test.com",
            name="David Outsider",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(
            self.student_submitter,
            self.student_teammate1,
            self.student_teammate2,
            self.student_outsider
        )

        self.project = Project.objects.create(
            section=self.section,
            title="Tagging Project",
            description="Testing teammate tagging",
            deadline=timezone.now() + timedelta(days=10)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Tag Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student_submitter)
        TeamMember.objects.create(team=self.team, user=self.student_teammate1)
        TeamMember.objects.create(team=self.team, user=self.student_teammate2)

        self.progress_url = f"/academic/student/team/{self.team.team_id}/progress/"

    def test_submit_deliverable_without_teammate_tags(self):
        """Submit deliverable without tagging teammates -> deliverable created with 0 contributions."""
        self.client.force_login(self.student_submitter)
        post_data = {
            'submit_deliverable': '1',
            'title': 'Solo Deliverable',
            'link': 'https://figma.com/file/solo',
            'description': 'Submitted individually'
        }
        resp = self.client.post(self.progress_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        deliverable = NonCodingDeliverable.objects.get(title='Solo Deliverable')
        self.assertEqual(deliverable.contributions.count(), 0)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Deliverable and contributions submitted successfully." in m for m in messages))

    def test_submit_deliverable_with_single_teammate_tag(self):
        """Submit deliverable with 1 teammate tagged -> DeliverableContribution created with status PENDING."""
        self.client.force_login(self.student_submitter)
        post_data = {
            'submit_deliverable': '1',
            'title': 'Figma Wireframes',
            'link': 'https://figma.com/file/wireframes',
            'description': 'Collaborative design',
            'teammate_id[]': [str(self.student_teammate1.pk)],
            'contribution_area[]': ['Designed Mobile UI Flow']
        }
        resp = self.client.post(self.progress_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        deliverable = NonCodingDeliverable.objects.get(title='Figma Wireframes')
        self.assertEqual(deliverable.contributions.count(), 1)

        claim = deliverable.contributions.first()
        self.assertEqual(claim.student, self.student_teammate1)
        self.assertEqual(claim.contribution_area, 'Designed Mobile UI Flow')
        self.assertEqual(claim.status, 'PENDING')

    def test_submit_deliverable_with_multiple_teammates_tagged(self):
        """Submit deliverable tagging multiple teammates with distinct contribution areas."""
        self.client.force_login(self.student_submitter)
        post_data = {
            'submit_deliverable': '1',
            'title': 'SRS Documentation',
            'link': 'https://docs.google.com/document/srs',
            'description': 'Full team SRS',
            'teammate_id[]': [str(self.student_teammate1.pk), str(self.student_teammate2.pk)],
            'contribution_area[]': ['Auth & Security Requirements', 'Database Schema Modeling']
        }
        resp = self.client.post(self.progress_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        deliverable = NonCodingDeliverable.objects.get(title='SRS Documentation')
        self.assertEqual(deliverable.contributions.count(), 2)

        claim1 = deliverable.contributions.get(student=self.student_teammate1)
        self.assertEqual(claim1.contribution_area, 'Auth & Security Requirements')
        self.assertEqual(claim1.status, 'PENDING')

        claim2 = deliverable.contributions.get(student=self.student_teammate2)
        self.assertEqual(claim2.contribution_area, 'Database Schema Modeling')
        self.assertEqual(claim2.status, 'PENDING')

    def test_security_cannot_tag_student_outside_team(self):
        """Security: A student not enrolled in this team cannot be tagged in a contribution claim."""
        self.client.force_login(self.student_submitter)
        post_data = {
            'submit_deliverable': '1',
            'title': 'Spoofed Deliverable',
            'link': 'https://example.com/spoof',
            'description': 'Attempting to tag outside user',
            'teammate_id[]': [str(self.student_outsider.pk)],
            'contribution_area[]': ['Fake Contribution']
        }
        resp = self.client.post(self.progress_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        deliverable = NonCodingDeliverable.objects.get(title='Spoofed Deliverable')
        # Outside student must be excluded by backend security check
        self.assertEqual(deliverable.contributions.count(), 0)

    def test_tagging_with_empty_contribution_area_rejected(self):
        """If a teammate is selected but the contribution area is empty, submission is rejected with an error message."""
        self.client.force_login(self.student_submitter)
        post_data = {
            'submit_deliverable': '1',
            'title': 'Incomplete Tag Deliverable',
            'link': 'https://example.com/incomplete',
            'description': 'Empty area',
            'teammate_id[]': [str(self.student_teammate1.pk)],
            'contribution_area[]': ['   ']
        }
        resp = self.client.post(self.progress_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Deliverable must NOT be created due to strict validation
        self.assertFalse(NonCodingDeliverable.objects.filter(title='Incomplete Tag Deliverable').exists())
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Submission failed: You must describe the contribution area" in m for m in messages))

    def test_tagging_with_no_teammate_selected_submits_cleanly(self):
        """When the empty option is selected in the teammate dropdown, deliverable is submitted cleanly without contributions."""
        self.client.force_login(self.student_submitter)
        post_data = {
            'submit_deliverable': '1',
            'title': 'No Tag Deliverable',
            'link': 'https://example.com/notag',
            'description': 'No teammate tagged',
            'teammate_id[]': [''],
            'contribution_area[]': ['']
        }
        resp = self.client.post(self.progress_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        deliverable = NonCodingDeliverable.objects.get(title='No Tag Deliverable')
        self.assertEqual(deliverable.contributions.count(), 0)

    def test_tagging_with_invalid_id_ignored_gracefully(self):
        """Non-numeric teammate ID is ignored gracefully without server error."""
        self.client.force_login(self.student_submitter)
        post_data = {
            'submit_deliverable': '1',
            'title': 'Bad ID Deliverable',
            'link': 'https://example.com/bad-id',
            'description': 'Bad teammate id',
            'teammate_id[]': ['invalid_id_string'],
            'contribution_area[]': ['Some area']
        }
        resp = self.client.post(self.progress_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        deliverable = NonCodingDeliverable.objects.get(title='Bad ID Deliverable')
        self.assertEqual(deliverable.contributions.count(), 0)

    def test_submit_and_tag_when_deadline_passed_blocked(self):
        """When project deadline has expired, submission and tagging are blocked."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=1)
        )
        self.client.force_login(self.student_submitter)
        post_data = {
            'submit_deliverable': '1',
            'title': 'Late Tagged Deliverable',
            'link': 'https://example.com/late',
            'teammate_id[]': [str(self.student_teammate1.pk)],
            'contribution_area[]': ['Late Area']
        }
        resp = self.client.post(self.progress_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(NonCodingDeliverable.objects.filter(title='Late Tagged Deliverable').count(), 0)
        self.assertEqual(DeliverableContribution.objects.count(), 0)


# =====================================================================
# 3. STUDENT DASHBOARD & PENDING CLAIMS DISPLAY TESTS
# =====================================================================
class DashboardPendingClaimsViewTests(TestCase):
    """Tests for the Pending Verifications alert box on student_dashboard."""

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_dash@test.com",
            name="Coordinator Dash",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_dash@test.com",
            name="Instructor Dash",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_submitter = User.objects.create_user(
            email="submitter_dash@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_tagged = User.objects.create_user(
            email="tagged_dash@test.com",
            name="Bob Tagged",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_other = User.objects.create_user(
            email="other_dash@test.com",
            name="Charlie Other",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student_submitter, self.student_tagged, self.student_other)

        self.project = Project.objects.create(
            section=self.section,
            title="Dashboard Project",
            description="Testing dashboard pending claims",
            deadline=timezone.now() + timedelta(days=7)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Dashboard Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student_submitter)
        TeamMember.objects.create(team=self.team, user=self.student_tagged)
        TeamMember.objects.create(team=self.team, user=self.student_other)

        self.deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_submitter,
            title="System Architecture Diagram",
            link="https://miro.com/board/arch-123",
            description="System components and flow"
        )
        self.claim = DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student_tagged,
            contribution_area="Created Microservices Diagram",
            status="PENDING"
        )
        self.dashboard_url = "/academic/student/dashboard/"

    def test_unauthenticated_redirected_to_login(self):
        """Unauthenticated user accessing student dashboard is redirected to login."""
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_tagged_student_sees_pending_claim_alert_box(self):
        """Tagged student visits dashboard and sees the Pending Verifications alert box."""
        self.client.force_login(self.student_tagged)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn("Action Required: Pending Verifications", content)
        self.assertIn("Alice Submitter", content)
        self.assertIn("System Architecture Diagram", content)
        self.assertIn("Created Microservices Diagram", content)
        self.assertIn("Dashboard Squad", content)

    def test_tagged_student_sees_verify_and_reject_buttons_when_active(self):
        """When project is active, tagged student sees action buttons to Verify and Reject."""
        self.client.force_login(self.student_tagged)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        verify_url = f"/academic/student/claim/{self.claim.pk}/verify/"
        reject_url = f"/academic/student/claim/{self.claim.pk}/reject/"
        self.assertIn(verify_url, content)
        self.assertIn(reject_url, content)
        self.assertIn("Verify", content)
        self.assertIn("Reject", content)

    def test_student_without_pending_claims_does_not_see_alert_box(self):
        """Submitter who was not tagged has 0 pending claims; alert box is omitted."""
        self.client.force_login(self.student_submitter)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertNotIn("Action Required: Pending Verifications", content)

    def test_other_teammate_does_not_see_someone_elses_pending_claims(self):
        """Charlie who was not tagged in this claim does not see Bob's pending claim."""
        self.client.force_login(self.student_other)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertNotIn("Action Required: Pending Verifications", content)
        self.assertNotIn("Created Microservices Diagram", content)

    def test_pending_claim_shows_project_locked_when_deadline_passed(self):
        """When project deadline has expired, dashboard renders Project Locked badge instead of buttons."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=1)
        )
        self.client.force_login(self.student_tagged)
        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn("Action Required: Pending Verifications", content)
        self.assertIn("Project Locked", content)
        verify_url = f"/academic/student/claim/{self.claim.pk}/verify/"
        reject_url = f"/academic/student/claim/{self.claim.pk}/reject/"
        self.assertNotIn(verify_url, content)
        self.assertNotIn(reject_url, content)


# =====================================================================
# 4. CLAIM VERIFICATION VIEW TESTS (verify_claim)
# =====================================================================
class VerifyClaimViewTests(TestCase):
    """Tests for the verify_claim action view."""

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_v@test.com",
            name="Coordinator V",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_v@test.com",
            name="Instructor V",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_submitter = User.objects.create_user(
            email="submitter_v@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_tagged = User.objects.create_user(
            email="tagged_v@test.com",
            name="Bob Tagged",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_other = User.objects.create_user(
            email="other_v@test.com",
            name="Charlie Other",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student_submitter, self.student_tagged, self.student_other)

        self.project = Project.objects.create(
            section=self.section,
            title="Verify Project",
            description="Testing claim verification",
            deadline=timezone.now() + timedelta(days=7)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Verify Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student_submitter)
        TeamMember.objects.create(team=self.team, user=self.student_tagged)

        self.deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_submitter,
            title="UI Mockups",
            link="https://figma.com/mockups"
        )
        self.claim = DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student_tagged,
            contribution_area="Created Design System",
            status="PENDING"
        )
        self.verify_url = f"/academic/student/claim/{self.claim.pk}/verify/"

    def test_verify_unauthenticated_redirected_to_login(self):
        """Unauthenticated user calling verify_claim is redirected to login."""
        resp = self.client.post(self.verify_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_verify_non_student_role_denied(self):
        """Instructor attempting to verify a student claim receives 403 Forbidden."""
        self.client.force_login(self.instructor)
        resp = self.client.post(self.verify_url)
        self.assertEqual(resp.status_code, 403)

    def test_verify_non_existent_claim_returns_404(self):
        """Attempting to verify non-existent claim ID returns 404."""
        self.client.force_login(self.student_tagged)
        resp = self.client.post("/academic/student/claim/99999/verify/")
        self.assertEqual(resp.status_code, 404)

    def test_security_cannot_verify_another_students_claim(self):
        """Student cannot verify a claim that belongs to another student -> returns 404."""
        self.client.force_login(self.student_other)
        resp = self.client.post(self.verify_url)
        self.assertEqual(resp.status_code, 404)

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, "PENDING")

    def test_verify_get_request_does_not_change_status(self):
        """GET request redirects to dashboard without modifying claim status."""
        self.client.force_login(self.student_tagged)
        resp = self.client.get(self.verify_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/academic/student/", resp.url)

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, "PENDING")

    def test_verify_post_when_deadline_active_updates_status_to_verified(self):
        """POST request when project active sets status to VERIFIED, adds success flash message, redirects."""
        self.client.force_login(self.student_tagged)
        resp = self.client.post(self.verify_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, "VERIFIED")

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any(f"Verified contribution for '{self.deliverable.title}'." in m for m in messages))

    def test_verify_post_when_deadline_passed_blocked(self):
        """POST request when deadline has passed does not verify; shows error message."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=1)
        )
        self.client.force_login(self.student_tagged)
        resp = self.client.post(self.verify_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, "PENDING")

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Cannot verify. The project deadline has passed." in m for m in messages))


# =====================================================================
# 5. CLAIM REJECTION VIEW TESTS (reject_claim)
# =====================================================================
class RejectClaimViewTests(TestCase):
    """Tests for the reject_claim action view."""

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_r@test.com",
            name="Coordinator R",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_r@test.com",
            name="Instructor R",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_submitter = User.objects.create_user(
            email="submitter_r@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_tagged = User.objects.create_user(
            email="tagged_r@test.com",
            name="Bob Tagged",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_other = User.objects.create_user(
            email="other_r@test.com",
            name="Charlie Other",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student_submitter, self.student_tagged, self.student_other)

        self.project = Project.objects.create(
            section=self.section,
            title="Reject Project",
            description="Testing claim rejection",
            deadline=timezone.now() + timedelta(days=7)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Reject Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student_submitter)
        TeamMember.objects.create(team=self.team, user=self.student_tagged)

        self.deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_submitter,
            title="SRS Document",
            link="https://docs.google.com/srs"
        )
        self.claim = DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student_tagged,
            contribution_area="Incorrectly Tagged Area",
            status="PENDING"
        )
        self.reject_url = f"/academic/student/claim/{self.claim.pk}/reject/"

    def test_reject_unauthenticated_redirected_to_login(self):
        """Unauthenticated user calling reject_claim is redirected to login."""
        resp = self.client.post(self.reject_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_reject_non_student_role_denied(self):
        """Instructor attempting to reject a student claim receives 403 Forbidden."""
        self.client.force_login(self.instructor)
        resp = self.client.post(self.reject_url)
        self.assertEqual(resp.status_code, 403)

    def test_reject_non_existent_claim_returns_404(self):
        """Attempting to reject non-existent claim ID returns 404."""
        self.client.force_login(self.student_tagged)
        resp = self.client.post("/academic/student/claim/99999/reject/")
        self.assertEqual(resp.status_code, 404)

    def test_security_cannot_reject_another_students_claim(self):
        """Student cannot reject a claim that belongs to another student -> returns 404."""
        self.client.force_login(self.student_other)
        resp = self.client.post(self.reject_url)
        self.assertEqual(resp.status_code, 404)

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, "PENDING")

    def test_reject_get_request_does_not_change_status(self):
        """GET request redirects to dashboard without modifying claim status."""
        self.client.force_login(self.student_tagged)
        resp = self.client.get(self.reject_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/academic/student/", resp.url)

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, "PENDING")

    def test_reject_post_when_deadline_active_updates_status_to_rejected(self):
        """POST request when project active sets status to REJECTED, adds flash message, redirects."""
        self.client.force_login(self.student_tagged)
        resp = self.client.post(self.reject_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, "REJECTED")

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any(f"Rejected contribution for '{self.deliverable.title}'." in m for m in messages))

    def test_reject_post_when_deadline_passed_blocked(self):
        """POST request when deadline has passed does not reject; shows error message."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=1)
        )
        self.client.force_login(self.student_tagged)
        resp = self.client.post(self.reject_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, "PENDING")

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Cannot reject. The project deadline has passed." in m for m in messages))


# =====================================================================
# 6. TEAM PROGRESS UI & BADGES DISPLAY TESTS
# =====================================================================
class SharedContributionsProgressUITests(TestCase):
    """Tests verify UI rendering of tagged contributions and status badges on student_progress."""

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_ui_c@test.com",
            name="Coordinator UI",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_ui_c@test.com",
            name="Instructor UI",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student1 = User.objects.create_user(
            email="student1_ui_c@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student2 = User.objects.create_user(
            email="student2_ui_c@test.com",
            name="Bob Teammate",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student1, self.student2)

        self.project = Project.objects.create(
            section=self.section,
            title="UI Badges Project",
            description="Testing progress badges",
            deadline=timezone.now() + timedelta(days=7)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Badge Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student1)
        TeamMember.objects.create(team=self.team, user=self.student2)

        self.deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student1,
            title="Shared Wireframes",
            link="https://figma.com/shared"
        )
        self.progress_url = f"/academic/student/team/{self.team.team_id}/progress/"

    def test_progress_page_renders_pending_badge(self):
        """When status is PENDING, progress page renders Pending badge with clock icon."""
        DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student2,
            contribution_area="Created UI Wireframe Drafts",
            status="PENDING"
        )
        self.client.force_login(self.student1)
        resp = self.client.get(self.progress_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn("Tagged Contributions:", content)
        self.assertIn("Bob Teammate", content)
        self.assertIn("Created UI Wireframe Drafts", content)
        self.assertIn("Pending", content)
        self.assertIn("fa-clock", content)

    def test_progress_page_renders_verified_badge(self):
        """When status is VERIFIED, progress page renders Verified badge with check icon."""
        DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student2,
            contribution_area="Created UI Wireframe Drafts",
            status="VERIFIED"
        )
        self.client.force_login(self.student1)
        resp = self.client.get(self.progress_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn("Bob Teammate", content)
        self.assertIn("Verified", content)
        self.assertIn("fa-check", content)

    def test_progress_page_renders_rejected_badge(self):
        """When status is REJECTED, progress page renders Rejected badge with xmark icon."""
        DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.student2,
            contribution_area="Created UI Wireframe Drafts",
            status="REJECTED"
        )
        self.client.force_login(self.student1)
        resp = self.client.get(self.progress_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn("Bob Teammate", content)
        self.assertIn("Rejected", content)
        self.assertIn("fa-xmark", content)

    def test_deliverable_without_contributions_omits_tagged_block(self):
        """If deliverable has no contributions, Tagged Contributions block is omitted."""
        self.client.force_login(self.student1)
        resp = self.client.get(self.progress_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertNotIn("Tagged Contributions:", content)

    def test_tag_dropdown_lists_teammates_excluding_current_user(self):
        """In the submission form, teammate dropdown lists other team members and excludes current user."""
        self.client.force_login(self.student1)
        resp = self.client.get(self.progress_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn(f'<option value="{self.student2.pk}">{self.student2.name}</option>', content)
        self.assertNotIn(f'<option value="{self.student1.pk}">{self.student1.name}</option>', content)


# =====================================================================
# 7. COMPLETE MULTI-STUDENT CONTRIBUTION LIFECYCLE INTEGRATION TEST
# =====================================================================
class SharedContributionFullLifecycleIntegrationTests(TestCase):
    """
    Complete end-to-end multi-student lifecycle:
    1. Submitter submits deliverable and tags Teammate A and Teammate B.
    2. Progress page shows both claims as PENDING.
    3. Teammate A logs into Dashboard -> sees Pending Claim -> clicks Verify.
    4. Teammate A's claim status updates to VERIFIED; pending box clears.
    5. Teammate B logs into Dashboard -> sees Pending Claim -> clicks Reject.
    6. Teammate B's claim status updates to REJECTED; pending box clears.
    7. All team members view Team Progress -> sees Teammate A as Verified, Teammate B as Rejected.
    8. Deadline passes -> verification/rejection attempts blocked.
    9. Deliverable deleted -> all contributions are cascade deleted.
    """

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_fl@test.com",
            name="Coordinator FL",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_fl@test.com",
            name="Instructor FL",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.submitter = User.objects.create_user(
            email="alice_fl@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.teammate_a = User.objects.create_user(
            email="bob_fl@test.com",
            name="Bob Verifier",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.teammate_b = User.objects.create_user(
            email="charlie_fl@test.com",
            name="Charlie Rejector",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.submitter, self.teammate_a, self.teammate_b)

        self.project = Project.objects.create(
            section=self.section,
            title="Full Shared Lifecycle Project",
            description="Testing full shared contribution cycle",
            deadline=timezone.now() + timedelta(days=10)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Lifecycle Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.submitter)
        TeamMember.objects.create(team=self.team, user=self.teammate_a)
        TeamMember.objects.create(team=self.team, user=self.teammate_b)

        self.progress_url = f"/academic/student/team/{self.team.team_id}/progress/"
        self.dashboard_url = "/academic/student/dashboard/"

    def test_full_shared_contribution_workflow_lifecycle(self):
        # Step 1: Submitter submits deliverable tagging Teammate A and Teammate B
        self.client.force_login(self.submitter)
        r = self.client.post(self.progress_url, {
            'submit_deliverable': '1',
            'title': 'Collaborative System Specification',
            'link': 'https://drive.google.com/spec-file',
            'description': 'Full team deliverable spec',
            'teammate_id[]': [str(self.teammate_a.pk), str(self.teammate_b.pk)],
            'contribution_area[]': ['Database Schema & ERD', 'Frontend Prototype Mockups']
        }, follow=True)
        self.assertEqual(r.status_code, 200)

        deliverable = NonCodingDeliverable.objects.get(title='Collaborative System Specification')
        self.assertEqual(deliverable.contributions.count(), 2)
        claim_a = deliverable.contributions.get(student=self.teammate_a)
        claim_b = deliverable.contributions.get(student=self.teammate_b)
        self.assertEqual(claim_a.status, 'PENDING')
        self.assertEqual(claim_b.status, 'PENDING')

        # Step 2: Verify team progress shows both as Pending
        r = self.client.get(self.progress_url)
        content_progress = r.content.decode()
        self.assertIn("Tagged Contributions:", content_progress)
        self.assertIn("Bob Verifier", content_progress)
        self.assertIn("Charlie Rejector", content_progress)
        self.assertIn("Pending", content_progress)

        # Step 3: Teammate A logs into Dashboard -> sees Pending Claim
        self.client.force_login(self.teammate_a)
        r = self.client.get(self.dashboard_url)
        content_dash_a = r.content.decode()
        self.assertIn("Action Required: Pending Verifications", content_dash_a)
        self.assertIn("Database Schema", content_dash_a)
        self.assertIn("Collaborative System Specification", content_dash_a)

        # Step 4: Teammate A verifies their claim
        verify_url_a = f"/academic/student/claim/{claim_a.pk}/verify/"
        r = self.client.post(verify_url_a, follow=True)
        self.assertEqual(r.status_code, 200)
        claim_a.refresh_from_db()
        self.assertEqual(claim_a.status, 'VERIFIED')

        # Step 5: Teammate A's dashboard now has 0 pending claims
        r = self.client.get(self.dashboard_url)
        self.assertNotIn("Action Required: Pending Verifications", r.content.decode())

        # Step 6: Teammate B logs into Dashboard -> sees Pending Claim
        self.client.force_login(self.teammate_b)
        r = self.client.get(self.dashboard_url)
        content_dash_b = r.content.decode()
        self.assertIn("Action Required: Pending Verifications", content_dash_b)
        self.assertIn("Frontend Prototype Mockups", content_dash_b)

        # Step 7: Teammate B rejects their claim
        reject_url_b = f"/academic/student/claim/{claim_b.pk}/reject/"
        r = self.client.post(reject_url_b, follow=True)
        self.assertEqual(r.status_code, 200)
        claim_b.refresh_from_db()
        self.assertEqual(claim_b.status, 'REJECTED')

        # Step 8: Teammate B's dashboard now has 0 pending claims
        r = self.client.get(self.dashboard_url)
        self.assertNotIn("Action Required: Pending Verifications", r.content.decode())

        # Step 9: View progress page -> Teammate A shows Verified, Teammate B shows Rejected
        self.client.force_login(self.submitter)
        r = self.client.get(self.progress_url)
        content_final = r.content.decode()
        self.assertIn("Bob Verifier", content_final)
        self.assertIn("Database Schema", content_final)
        self.assertIn("Verified", content_final)
        self.assertIn("Charlie Rejector", content_final)
        self.assertIn("Frontend Prototype Mockups", content_final)
        self.assertIn("Rejected", content_final)

        # Step 10: Fast-forward deadline to the past
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(minutes=5)
        )
        self.project.refresh_from_db()

        # Step 11: Verification/Rejection after deadline blocked
        claim_a.status = 'PENDING'
        claim_a.save()
        self.client.force_login(self.teammate_a)
        r = self.client.post(verify_url_a, follow=True)
        claim_a.refresh_from_db()
        self.assertEqual(claim_a.status, 'PENDING')
        self.assertTrue(any("Cannot verify. The project deadline has passed." in m for m in [msg.message for msg in get_messages(r.wsgi_request)]))

        # Step 12: Delete deliverable -> contributions cascade deleted
        del_url = f"/academic/student/deliverable/{deliverable.pk}/delete/"
        self.client.force_login(self.submitter)
        # Re-activate deadline temporarily to delete
        Project.objects.filter(pk=self.project.pk).update(deadline=timezone.now() + timedelta(days=1))
        r = self.client.post(del_url, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(NonCodingDeliverable.objects.filter(pk=deliverable.pk).exists())
        self.assertEqual(DeliverableContribution.objects.count(), 0)



# =====================================================================
# 8. INSTRUCTOR DELIVERABLES & PEER REVIEW VIEW TESTS
# =====================================================================
class InstructorDeliverablesReviewViewTests(TestCase):
    """Unit and security tests for team_deliverables_review view."""

    def setUp(self):
        self.coordinator = User.objects.create_user(
            email="coord_review@test.com",
            name="Coordinator Review",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_review@test.com",
            name="Instructor Review",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.admin = User.objects.create_user(
            email="admin_review@test.com",
            name="Admin Review",
            role=User.Role.ADMIN,
            password="password123"
        )
        self.student1 = User.objects.create_user(
            email="student1_rev@test.com",
            name="Alice Student",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student2 = User.objects.create_user(
            email="student2_rev@test.com",
            name="Bob Student",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student1, self.student2)

        self.project = Project.objects.create(
            section=self.section,
            title="Peer Review Project",
            description="Testing deliverables review view",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Gamma Review Team"
        )
        TeamMember.objects.create(team=self.team, user=self.student1)
        TeamMember.objects.create(team=self.team, user=self.student2)

        self.deliv1 = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student1,
            title="UI Prototypes",
            link="https://figma.com/file/review-ui",
            description="High fidelity Figma mockups"
        )
        self.claim_pending = DeliverableContribution.objects.create(
            deliverable=self.deliv1,
            student=self.student2,
            contribution_area="Created mobile layout wireframes",
            status='PENDING'
        )

        self.deliv2 = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student2,
            title="Database Schema ERD",
            link="https://dbdocs.io/review-db",
            description="PostgreSQL schema specification"
        )
        self.claim_verified = DeliverableContribution.objects.create(
            deliverable=self.deliv2,
            student=self.student1,
            contribution_area="Designed tables and normalization",
            status='VERIFIED'
        )
        self.claim_rejected = DeliverableContribution.objects.create(
            deliverable=self.deliv2,
            student=self.student2,
            contribution_area="Reviewed indexing strategies",
            status='REJECTED'
        )

        self.url = f"/academic/instructor/team/{self.team.team_id}/deliverables/"

    def test_unauthenticated_user_redirected_to_login(self):
        """Unauthenticated user is redirected to the login page."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_student_access_denied_redirects_to_student_dashboard(self):
        """Students cannot access the instructor deliverables review page."""
        self.client.force_login(self.student1)
        resp = self.client.get(self.url, follow=True)
        self.assertEqual(resp.status_code, 200)
        # Redirected to student dashboard
        self.assertTrue(any("Access denied. Instructor privileges required." in m for m in [msg.message for msg in get_messages(resp.wsgi_request)]))

    def test_instructor_can_access_deliverables_review_page(self):
        """Instructor can view all team deliverables and contributions."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Deliverables & Peer Reviews", content)
        self.assertIn("UI Prototypes", content)
        self.assertIn("Database Schema ERD", content)
        self.assertIn("Created mobile layout wireframes", content)
        self.assertIn("Designed tables and normalization", content)

    def test_coordinator_and_admin_can_access(self):
        """Both coordinator and admin have access permissions."""
        for user in [self.coordinator, self.admin]:
            self.client.force_login(user)
            resp = self.client.get(self.url)
            self.assertEqual(resp.status_code, 200)

    def test_filter_by_all_claims(self):
        """status=ALL returns all deliverables with all contributions."""
        self.client.force_login(self.instructor)
        resp = self.client.get(f"{self.url}?status=ALL")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['deliverables']), 2)

    def test_filter_by_pending_status(self):
        """status=PENDING only displays deliverables that have pending claims."""
        self.client.force_login(self.instructor)
        resp = self.client.get(f"{self.url}?status=PENDING")
        self.assertEqual(resp.status_code, 200)
        deliverables = resp.context['deliverables']
        self.assertEqual(len(deliverables), 1)
        self.assertEqual(deliverables[0].pk, self.deliv1.pk)
        self.assertEqual(len(deliverables[0].filtered_contributions), 1)
        self.assertEqual(deliverables[0].filtered_contributions[0].status, 'PENDING')

    def test_filter_by_verified_status(self):
        """status=VERIFIED only displays deliverables that have verified claims."""
        self.client.force_login(self.instructor)
        resp = self.client.get(f"{self.url}?status=VERIFIED")
        self.assertEqual(resp.status_code, 200)
        deliverables = resp.context['deliverables']
        self.assertEqual(len(deliverables), 1)
        self.assertEqual(deliverables[0].pk, self.deliv2.pk)
        self.assertEqual(len(deliverables[0].filtered_contributions), 1)
        self.assertEqual(deliverables[0].filtered_contributions[0].status, 'VERIFIED')

    def test_filter_by_rejected_status(self):
        """status=REJECTED only displays deliverables that have rejected claims."""
        self.client.force_login(self.instructor)
        resp = self.client.get(f"{self.url}?status=REJECTED")
        self.assertEqual(resp.status_code, 200)
        deliverables = resp.context['deliverables']
        self.assertEqual(len(deliverables), 1)
        self.assertEqual(deliverables[0].pk, self.deliv2.pk)
        self.assertEqual(len(deliverables[0].filtered_contributions), 1)
        self.assertEqual(deliverables[0].filtered_contributions[0].status, 'REJECTED')

    def test_nonexistent_team_returns_404(self):
        """Requesting review for a non-existent team returns 404."""
        self.client.force_login(self.instructor)
        resp = self.client.get("/academic/instructor/team/99999/deliverables/")
        self.assertEqual(resp.status_code, 404)


# =====================================================================
# 9. LIVE SELENIUM BROWSER E2E WORKFLOW TESTS
# =====================================================================
class SharedContributionSeleniumE2ETests(StaticLiveServerTestCase):
    """End-to-end browser tests verifying UI tagging, pending notification, and verification."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--log-level=3")

        service = Service(ChromeDriverManager().install())
        cls.driver = webdriver.Chrome(service=service, options=options)
        cls.wait = WebDriverWait(cls.driver, 20)

    @classmethod
    def tearDownClass(cls):
        if cls.driver:
            cls.driver.quit()
        super().tearDownClass()

    def setUp(self):
        self.coordinator = User.objects.create_user(
            email="coord_se2e@test.com",
            name="Coordinator SE2E",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_se2e@test.com",
            name="Instructor SE2E",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_submitter = User.objects.create_user(
            email="alice_se2e@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_teammate = User.objects.create_user(
            email="bob_se2e@test.com",
            name="Bob Contributor",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student_submitter, self.student_teammate)

        self.project = Project.objects.create(
            section=self.section,
            title="Selenium Shared Project",
            description="Testing live tagging and verification",
            deadline=timezone.now() + timedelta(days=10)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Selenium Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student_submitter)
        TeamMember.objects.create(team=self.team, user=self.student_teammate)

    def _login(self, email, password):
        self.driver.get(f"{self.live_server_url}/accounts/login/")
        user_field = self.wait.until(EC.presence_of_element_located((By.NAME, "username")))
        pass_field = self.driver.find_element(By.NAME, "password")
        submit_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")

        user_field.clear()
        user_field.send_keys(email)
        pass_field.clear()
        pass_field.send_keys(password)
        submit_btn.click()

        self.wait.until(lambda d: "/accounts/login/" not in d.current_url)

    def _logout(self):
        try:
            sign_out_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Sign Out')]")))
            sign_out_btn.click()
            self.wait.until(lambda d: "/accounts/login/" in d.current_url)
        except Exception:
            self.driver.delete_all_cookies()
            self.driver.get(f"{self.live_server_url}/accounts/login/")

    def test_shared_deliverable_e2e_tagging_and_verification_workflow(self):
        """
        E2E Browser Test:
        1. Login as Alice (Submitter).
        2. Navigate to Team Progress.
        3. Fill in Deliverable form (Title, Link, Description).
        4. Select Bob from Teammate dropdown and type contribution area.
        5. Submit Deliverable -> verify listed with Bob's 'Pending' badge.
        6. Logout Alice.
        7. Login as Bob (Contributor).
        8. Bob lands on Dashboard -> sees 'Action Required: Pending Verifications' alert box.
        9. Bob clicks 'Verify' button.
        10. Verify success flash message appears and alert box is cleared.
        11. Navigate to Team Progress page -> verify Bob's badge is now 'Verified'.
        """
        # 1. Login as Alice
        self._login("alice_se2e@test.com", "password123")

        # 2. Go to Team Progress
        progress_url = f"{self.live_server_url}/academic/student/team/{self.team.team_id}/progress/"
        self.driver.get(progress_url)
        self.wait.until(EC.presence_of_element_located((By.NAME, "title")))

        # 3. Fill Deliverable form
        self.driver.find_element(By.NAME, "title").send_keys("Architecture Specification E2E")
        self.driver.find_element(By.NAME, "link").send_keys("https://figma.com/arch-e2e")
        self.driver.find_element(By.NAME, "description").send_keys("Architecture doc with tagged teammate")

        # 4. Tag Bob from dropdown
        teammate_select_el = self.driver.find_element(By.NAME, "teammate_id[]")
        select = Select(teammate_select_el)
        select.select_by_value(str(self.student_teammate.pk))

        area_input = self.driver.find_element(By.NAME, "contribution_area[]")
        area_input.send_keys("Designed Database Schemas & Migrations")

        # 5. Submit Deliverable
        submit_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Submit Deliverable')]")
        submit_btn.click()

        # Wait for page reload and success message
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Deliverable and contributions submitted successfully.')]")))

        # Verify listed with Bob and Pending badge
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Architecture Specification E2E", body_text)
        self.assertIn("Bob Contributor", body_text)
        self.assertIn("Designed Database Schemas & Migrations", body_text)
        self.assertIn("Pending", body_text)

        # 6. Logout Alice
        self._logout()

        # 7. Login as Bob
        self._login("bob_se2e@test.com", "password123")

        # 8. Check Dashboard for Pending Claim alert box
        dashboard_url = f"{self.live_server_url}/academic/student/dashboard/"
        self.driver.get(dashboard_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(., 'Pending Verifications')]")))

        dash_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Alice Submitter", dash_text)
        self.assertIn("Architecture Specification E2E", dash_text)
        self.assertIn("Designed Database Schemas & Migrations", dash_text)

        # 9. Bob clicks Verify button
        verify_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Verify')]")))
        verify_btn.click()

        # 10. Verify success flash message appears
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Verified contribution for')]")))

        # Alert box is cleared
        dash_text_after = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertNotIn("Action Required: Pending Verifications", dash_text_after)

        # 11. Navigate to Team Progress
        self.driver.get(progress_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h4[contains(text(), 'Architecture Specification E2E')]")))

        # 12. Verify Bob's badge is now Verified
        progress_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Bob Contributor", progress_text)
        self.assertIn("Designed Database Schemas & Migrations", progress_text)
        self.assertIn("Verified", progress_text)
