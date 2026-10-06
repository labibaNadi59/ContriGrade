import os
import sys
import unittest
from datetime import timedelta
from unittest.mock import patch, MagicMock

import django
from django.test import TestCase, Client
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError

from accounts.models import User
from academic.models import Course, CourseSection, Project, Team, TeamMember, NonCodingDeliverable
from academic.forms import NonCodingDeliverableForm

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# =====================================================================
# 1. MODEL UNIT TESTS
# =====================================================================
class NonCodingDeliverableModelTests(TestCase):
    """Unit tests for the NonCodingDeliverable model."""

    def setUp(self):
        self.coordinator = User.objects.create_user(
            email="coord_model@test.com",
            name="Coordinator Test",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_model@test.com",
            name="Instructor Test",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student = User.objects.create_user(
            email="student_model@test.com",
            name="Student Test",
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
        self.section.students.add(self.student)
        self.project = Project.objects.create(
            section=self.section,
            title="Hospital Management",
            description="Term project",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Alpha Team"
        )
        self.membership = TeamMember.objects.create(
            team=self.team,
            user=self.student
        )

    def test_deliverable_creation_and_attributes(self):
        """Test creating a NonCodingDeliverable with all attributes populated."""
        deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student,
            title="SRS Document",
            link="https://docs.google.com/document/d/xyz",
            description="Complete system requirements specification document."
        )
        self.assertIsNotNone(deliverable.pk)
        self.assertEqual(deliverable.team, self.team)
        self.assertEqual(deliverable.submitted_by, self.student)
        self.assertEqual(deliverable.title, "SRS Document")
        self.assertEqual(deliverable.link, "https://docs.google.com/document/d/xyz")
        self.assertEqual(deliverable.description, "Complete system requirements specification document.")
        self.assertIsNotNone(deliverable.submitted_at)

    def test_deliverable_str_representation(self):
        """Test that __str__ returns 'title (team_name)'."""
        deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student,
            title="Figma Wireframes",
            link="https://figma.com/file/123"
        )
        self.assertEqual(str(deliverable), "Figma Wireframes (Alpha Team)")

    def test_deliverable_optional_description_default(self):
        """Test that description defaults to empty string when omitted."""
        deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student,
            title="Presentation Slides",
            link="https://canva.com/design/456"
        )
        self.assertEqual(deliverable.description, "")

    def test_deliverable_auto_now_add_timestamp(self):
        """Test that submitted_at is automatically timestamped."""
        before = timezone.now()
        deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student,
            title="Architecture Diagram",
            link="https://miro.com/board/789"
        )
        after = timezone.now()
        self.assertTrue(before <= deliverable.submitted_at <= after)

    def test_cascade_delete_team(self):
        """Test that deleting a team cascades to delete its deliverables."""
        NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student,
            title="SRS Document",
            link="https://docs.google.com/document/d/xyz"
        )
        self.assertEqual(NonCodingDeliverable.objects.filter(team=self.team).count(), 1)
        self.team.delete()
        self.assertEqual(NonCodingDeliverable.objects.count(), 0)

    def test_cascade_delete_submitter(self):
        """Test that deleting the submitter user cascades to delete their deliverables."""
        deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student,
            title="SRS Document",
            link="https://docs.google.com/document/d/xyz"
        )
        self.student.delete()
        self.assertFalse(NonCodingDeliverable.objects.filter(pk=deliverable.pk).exists())

    def test_multiple_deliverables_same_team(self):
        """Test that a team can have multiple deliverables."""
        NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student,
            title="Deliverable 1",
            link="https://example.com/1"
        )
        NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student,
            title="Deliverable 2",
            link="https://example.com/2"
        )
        self.assertEqual(self.team.deliverables.count(), 2)


# =====================================================================
# 2. FORM UNIT TESTS
# =====================================================================
class NonCodingDeliverableFormTests(TestCase):
    """Unit tests for the NonCodingDeliverableForm."""

    def test_valid_form_data(self):
        """Test that valid title, URL link, and description produce a valid form."""
        form = NonCodingDeliverableForm(data={
            'title': 'Figma UI Prototype',
            'link': 'https://www.figma.com/design/test-file',
            'description': 'Mobile & desktop wireframes'
        })
        self.assertTrue(form.is_valid())

    def test_valid_form_with_empty_description(self):
        """Test that description is optional and empty string is accepted."""
        form = NonCodingDeliverableForm(data={
            'title': 'SRS Document',
            'link': 'https://docs.google.com/document/d/123456',
            'description': ''
        })
        self.assertTrue(form.is_valid())

    def test_blank_title_invalid(self):
        """Test that missing title causes validation error."""
        form = NonCodingDeliverableForm(data={
            'title': '',
            'link': 'https://docs.google.com/document/d/123456',
            'description': 'Some notes'
        })
        self.assertFalse(form.is_valid())
        self.assertIn('title', form.errors)
        self.assertEqual(form.errors['title'][0], 'This field is required.')

    def test_blank_link_invalid(self):
        """Test that missing link URL causes validation error."""
        form = NonCodingDeliverableForm(data={
            'title': 'Figma Wireframes',
            'link': '',
            'description': 'Some notes'
        })
        self.assertFalse(form.is_valid())
        self.assertIn('link', form.errors)
        self.assertEqual(form.errors['link'][0], 'This field is required.')

    def test_invalid_url_format_rejected(self):
        """Test that malformed URLs are rejected by URLField validation."""
        bad_urls = [
            'not_a_url',
            'htt://missing-p.com',
            'javascript:alert(1)',
        ]
        for url in bad_urls:
            form = NonCodingDeliverableForm(data={
                'title': 'Project Spec',
                'link': url,
                'description': 'Notes'
            })
            self.assertFalse(form.is_valid(), f"Expected '{url}' to fail validation")
            self.assertIn('link', form.errors)
            self.assertIn('Enter a valid URL', form.errors['link'][0])

    def test_valid_url_schemes_accepted(self):
        """Test that standard HTTP and HTTPS URLs from various deliverable services are accepted."""
        valid_urls = [
            'https://figma.com/file/abc',
            'https://docs.google.com/document/d/1iohb_qlT3iu6woA0jtXkJDF3QawdtYHR/edit',
            'https://canva.link/1t4c71ig7dqoc85',
            'http://example.com/spec.pdf',
            'https://miro.com/app/board/uXjVO123='
        ]
        for url in valid_urls:
            form = NonCodingDeliverableForm(data={
                'title': 'Deliverable Test',
                'link': url,
                'description': ''
            })
            self.assertTrue(form.is_valid(), f"Expected '{url}' to be valid")


# =====================================================================
# 3. SUBMISSION VIEW & WORKFLOW TESTS (student_team_progress)
# =====================================================================
class DeliverableSubmissionViewTests(TestCase):
    """Workflow and security tests for submitting deliverables in student_team_progress."""

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_sub@test.com",
            name="Coordinator Sub",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_sub@test.com",
            name="Instructor Sub",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_member = User.objects.create_user(
            email="member_sub@test.com",
            name="Student Member",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_other = User.objects.create_user(
            email="other_sub@test.com",
            name="Student Other",
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
        self.section.students.add(self.student_member, self.student_other)

        self.project = Project.objects.create(
            section=self.section,
            title="Deliverable Project",
            description="Testing deliverables",
            deadline=timezone.now() + timedelta(days=7)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Dev Squad"
        )
        self.membership = TeamMember.objects.create(
            team=self.team,
            user=self.student_member
        )
        self.url = f"/academic/student/team/{self.team.team_id}/progress/"

    def test_unauthenticated_user_redirected_to_login(self):
        """Unauthenticated user accessing team progress is redirected to login."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_instructor_access_denied(self):
        """Instructors are blocked from student progress view via @student_required."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_coordinator_access_denied(self):
        """Coordinators are blocked from student progress view via @student_required."""
        self.client.force_login(self.coordinator)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_unauthorized_student_other_team_returns_404(self):
        """A student who is not a member of the team cannot access that team's progress page."""
        self.client.force_login(self.student_other)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 404)

    def test_authorized_student_get_shows_submission_form_when_active(self):
        """Authorized student loads page and sees the deliverable submission form and empty state."""
        self.client.force_login(self.student_member)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Submit Deliverable", content)
        self.assertIn("submit_deliverable", content)
        self.assertIn("Title *", content)
        self.assertIn("Link (URL) *", content)
        self.assertIn("No non-coding deliverables have been submitted yet.", content)

    def test_authorized_student_get_accessible_without_github_repo(self):
        """Team without linked GitHub repo can still view deliverables section."""
        self.assertFalse(bool(self.team.github_repo_url))
        self.client.force_login(self.student_member)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Your team has not linked a GitHub repository yet.", content)
        self.assertIn("Submit Deliverable", content)
        self.assertIn("Submitted Deliverables", content)

    def test_authorized_student_get_lists_existing_deliverables(self):
        """Existing deliverables appear in the list with title, author, and link."""
        NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_member,
            title="SRS Document v1.0",
            link="https://docs.google.com/document/d/srs-demo",
            description="Initial requirements drafted."
        )
        self.client.force_login(self.student_member)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("SRS Document v1.0", content)
        self.assertIn("Student Member", content)
        self.assertIn("https://docs.google.com/document/d/srs-demo", content)
        self.assertIn("Initial requirements drafted.", content)
        self.assertIn("1 Items", content)

    def test_post_valid_deliverable_creates_record_and_redirects(self):
        """POST with valid data saves the deliverable, associates user and team, and redirects."""
        self.client.force_login(self.student_member)
        post_data = {
            'submit_deliverable': '1',
            'title': 'Figma UI Wireframes',
            'link': 'https://www.figma.com/file/wireframes-123',
            'description': 'Mobile and Desktop layouts'
        }
        resp = self.client.post(self.url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Check DB entry
        deliverables = NonCodingDeliverable.objects.filter(team=self.team)
        self.assertEqual(deliverables.count(), 1)
        created = deliverables.first()
        self.assertEqual(created.title, 'Figma UI Wireframes')
        self.assertEqual(created.link, 'https://www.figma.com/file/wireframes-123')
        self.assertEqual(created.description, 'Mobile and Desktop layouts')
        self.assertEqual(created.submitted_by, self.student_member)
        self.assertEqual(created.team, self.team)

        # Check flash message
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Deliverable submitted successfully." in m for m in messages))

    def test_post_invalid_missing_title_shows_error_no_db_entry(self):
        """POST with missing title fails validation, shows form error, does not create DB entry."""
        self.client.force_login(self.student_member)
        post_data = {
            'submit_deliverable': '1',
            'title': '',
            'link': 'https://www.figma.com/file/123',
            'description': 'Notes'
        }
        resp = self.client.post(self.url, post_data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(NonCodingDeliverable.objects.filter(team=self.team).count(), 0)
        content = resp.content.decode('utf-8')
        self.assertIn("This field is required.", content)

    def test_post_invalid_bad_url_shows_error_no_db_entry(self):
        """POST with malformed URL fails validation, shows error, does not create DB entry."""
        self.client.force_login(self.student_member)
        post_data = {
            'submit_deliverable': '1',
            'title': 'My Deliverable',
            'link': 'invalid-url-string',
            'description': 'Notes'
        }
        resp = self.client.post(self.url, post_data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(NonCodingDeliverable.objects.filter(team=self.team).count(), 0)
        content = resp.content.decode('utf-8')
        self.assertIn("Enter a valid URL", content)

    def test_post_when_deadline_passed_blocked_with_flash_message(self):
        """When project deadline has expired, POST submission is blocked and no record is created."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=2)
        )
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_active())

        self.client.force_login(self.student_member)
        post_data = {
            'submit_deliverable': '1',
            'title': 'Late Submission',
            'link': 'https://figma.com/late',
            'description': 'Tried submitting late'
        }
        resp = self.client.post(self.url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(NonCodingDeliverable.objects.filter(team=self.team).count(), 0)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Submissions locked. The deadline" in m for m in messages))

    def test_get_when_deadline_passed_shows_locked_banner_and_hides_form(self):
        """When deadline has passed, submission form is replaced by locked notification."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=2)
        )
        self.client.force_login(self.student_member)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Submissions Locked (Deadline Passed)", content)
        self.assertNotIn("Submit Deliverable</button>", content)


# =====================================================================
# 4. EDIT DELIVERABLE WORKFLOW TESTS
# =====================================================================
class EditDeliverableWorkflowTests(TestCase):
    """Unit and security tests for edit_deliverable view."""

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_edit@test.com",
            name="Coordinator Edit",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_edit@test.com",
            name="Instructor Edit",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_owner = User.objects.create_user(
            email="owner_edit@test.com",
            name="Student Owner",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_teammate = User.objects.create_user(
            email="teammate_edit@test.com",
            name="Student Teammate",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_other = User.objects.create_user(
            email="other_edit@test.com",
            name="Student Other",
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
        self.section.students.add(self.student_owner, self.student_teammate, self.student_other)

        self.project = Project.objects.create(
            section=self.section,
            title="Edit Project",
            description="Testing edit",
            deadline=timezone.now() + timedelta(days=7)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Code Wizards"
        )
        TeamMember.objects.create(team=self.team, user=self.student_owner)
        TeamMember.objects.create(team=self.team, user=self.student_teammate)

        self.deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_owner,
            title="Original Title",
            link="https://figma.com/original",
            description="Original Description"
        )
        self.edit_url = f"/academic/student/deliverable/{self.deliverable.pk}/edit/"

    def test_edit_unauthenticated_redirected_to_login(self):
        """Unauthenticated user is redirected to login."""
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_edit_instructor_denied(self):
        """Instructor is denied access to student deliverable editing."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 403)

    def test_edit_non_existent_deliverable_returns_404(self):
        """Accessing a non-existent deliverable ID returns 404."""
        self.client.force_login(self.student_owner)
        resp = self.client.get("/academic/student/deliverable/99999/edit/")
        self.assertEqual(resp.status_code, 404)

    def test_edit_by_teammate_blocked_by_security_rule(self):
        """Teammate on the same team cannot edit a deliverable submitted by another student."""
        self.client.force_login(self.student_teammate)
        resp = self.client.get(self.edit_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Security block: You can only edit your own submissions." in m for m in messages))

        # Ensure database record remains unchanged
        self.deliverable.refresh_from_db()
        self.assertEqual(self.deliverable.title, "Original Title")

    def test_edit_by_outside_student_blocked_by_security_rule(self):
        """Student from an unrelated team cannot edit the deliverable."""
        self.client.force_login(self.student_other)
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"/academic/student/team/{self.team.team_id}/progress/", resp.url)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Security block: You can only edit your own submissions." in m for m in messages))

    def test_edit_when_deadline_passed_blocked(self):
        """Owner cannot edit their own deliverable after the project deadline has expired."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=1)
        )
        self.deliverable.refresh_from_db()

        self.client.force_login(self.student_owner)
        resp = self.client.get(self.edit_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Editing is locked. The project deadline has passed." in m for m in messages))

    def test_edit_get_prepopulated_form_success(self):
        """Owner can load the edit page and sees existing title, link, and description."""
        self.client.force_login(self.student_owner)
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Edit Deliverable", content)
        self.assertIn("Original Title", content)
        self.assertIn("https://figma.com/original", content)
        self.assertIn("Original Description", content)
        self.assertIn("Save Changes", content)

    def test_edit_post_valid_updates_database_and_redirects(self):
        """Owner submits updated fields: DB is updated, success flash message shown, redirects."""
        self.client.force_login(self.student_owner)
        update_data = {
            'title': 'Updated Title Final',
            'link': 'https://figma.com/updated-v2',
            'description': 'Updated Notes and Revisions'
        }
        resp = self.client.post(self.edit_url, update_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.deliverable.refresh_from_db()
        self.assertEqual(self.deliverable.title, 'Updated Title Final')
        self.assertEqual(self.deliverable.link, 'https://figma.com/updated-v2')
        self.assertEqual(self.deliverable.description, 'Updated Notes and Revisions')

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Successfully updated 'Updated Title Final'." in m for m in messages))
