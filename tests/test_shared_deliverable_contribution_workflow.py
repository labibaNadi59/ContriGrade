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


