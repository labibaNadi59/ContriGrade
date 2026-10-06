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

    def test_edit_post_invalid_url_shows_error_and_does_not_save(self):
        """Owner posts invalid data: form error shown, DB remains unchanged."""
        self.client.force_login(self.student_owner)
        update_data = {
            'title': 'New Title',
            'link': 'bad-url',
            'description': 'Notes'
        }
        resp = self.client.post(self.edit_url, update_data)
        self.assertEqual(resp.status_code, 200)

        self.deliverable.refresh_from_db()
        self.assertEqual(self.deliverable.title, 'Original Title')
        content = resp.content.decode('utf-8')
        self.assertIn("Enter a valid URL", content)


# =====================================================================
# 5. DELETE DELIVERABLE WORKFLOW TESTS
# =====================================================================
class DeleteDeliverableWorkflowTests(TestCase):
    """Unit and security tests for delete_deliverable view."""

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_del@test.com",
            name="Coordinator Del",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_del@test.com",
            name="Instructor Del",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_owner = User.objects.create_user(
            email="owner_del@test.com",
            name="Student Owner",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_teammate = User.objects.create_user(
            email="teammate_del@test.com",
            name="Student Teammate",
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
        self.section.students.add(self.student_owner, self.student_teammate)

        self.project = Project.objects.create(
            section=self.section,
            title="Delete Project",
            description="Testing delete",
            deadline=timezone.now() + timedelta(days=7)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Delete Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student_owner)
        TeamMember.objects.create(team=self.team, user=self.student_teammate)

        self.deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_owner,
            title="Deliverable to Delete",
            link="https://docs.google.com/test",
            description="Will be removed"
        )
        self.del_url = f"/academic/student/deliverable/{self.deliverable.pk}/delete/"

    def test_delete_unauthenticated_redirected_to_login(self):
        """Unauthenticated user redirected to login."""
        resp = self.client.get(self.del_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_delete_instructor_denied(self):
        """Instructor is blocked from deleting student deliverable."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.del_url)
        self.assertEqual(resp.status_code, 403)

    def test_delete_non_existent_deliverable_returns_404(self):
        """Accessing a non-existent deliverable ID returns 404."""
        self.client.force_login(self.student_owner)
        resp = self.client.get("/academic/student/deliverable/99999/delete/")
        self.assertEqual(resp.status_code, 404)

    def test_delete_by_teammate_blocked_by_security_rule(self):
        """Teammate cannot delete another student's submission."""
        self.client.force_login(self.student_teammate)
        resp = self.client.post(self.del_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Record must still exist
        self.assertTrue(NonCodingDeliverable.objects.filter(pk=self.deliverable.pk).exists())
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Security block: You can only delete your own submissions." in m for m in messages))

    def test_delete_by_outside_student_blocked_by_security_rule(self):
        """Student from an unrelated team cannot delete the deliverable."""
        student_other = User.objects.create_user(
            email="other_del@test.com",
            name="Student Other",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.section.students.add(student_other)
        self.client.force_login(student_other)
        resp = self.client.post(self.del_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"/academic/student/team/{self.team.team_id}/progress/", resp.url)
        self.assertTrue(NonCodingDeliverable.objects.filter(pk=self.deliverable.pk).exists())
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Security block: You can only delete your own submissions." in m for m in messages))

    def test_delete_when_deadline_passed_blocked(self):
        """Owner cannot delete submission once the project deadline has expired."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=1)
        )
        self.deliverable.refresh_from_db()

        self.client.force_login(self.student_owner)
        resp = self.client.post(self.del_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.assertTrue(NonCodingDeliverable.objects.filter(pk=self.deliverable.pk).exists())
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Deleting is locked. The project deadline has passed." in m for m in messages))

    def test_delete_get_confirmation_page_success(self):
        """Owner GETs confirmation page, sees deliverable title and warning."""
        self.client.force_login(self.student_owner)
        resp = self.client.get(self.del_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Delete Deliverable?", content)
        self.assertIn("Deliverable to Delete", content)
        self.assertIn("Yes, Delete It", content)
        self.assertIn("Cancel", content)

    def test_delete_post_deletes_record_and_redirects(self):
        """Owner submits POST: record deleted from DB, flash message shown, redirects to team progress."""
        self.client.force_login(self.student_owner)
        resp = self.client.post(self.del_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.assertFalse(NonCodingDeliverable.objects.filter(pk=self.deliverable.pk).exists())
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Deliverable successfully removed." in m for m in messages))


# =====================================================================
# 6. UI BUTTON VISIBILITY & TEAMMATE PERMISSIONS TESTS
# =====================================================================
class DeliverableUIPermissionsTests(TestCase):
    """Tests verify that edit/delete buttons are conditionally shown only to the owner and when active."""

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_ui@test.com",
            name="Coordinator UI",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_ui@test.com",
            name="Instructor UI",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_a = User.objects.create_user(
            email="student_a@test.com",
            name="Student Alice",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_b = User.objects.create_user(
            email="student_b@test.com",
            name="Student Bob",
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
        self.section.students.add(self.student_a, self.student_b)

        self.project = Project.objects.create(
            section=self.section,
            title="UI Project",
            description="Testing UI buttons",
            deadline=timezone.now() + timedelta(days=7)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="UI Team"
        )
        TeamMember.objects.create(team=self.team, user=self.student_a)
        TeamMember.objects.create(team=self.team, user=self.student_b)

        self.deliverable_a = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_a,
            title="Alice Deliverable",
            link="https://alice.link/doc"
        )
        self.url = f"/academic/student/team/{self.team.team_id}/progress/"

    def test_submitter_sees_edit_and_delete_buttons_when_active(self):
        """Alice sees edit and delete buttons for her own deliverable when deadline is active."""
        self.client.force_login(self.student_a)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        edit_link = f"/academic/student/deliverable/{self.deliverable_a.pk}/edit/"
        del_link = f"/academic/student/deliverable/{self.deliverable_a.pk}/delete/"
        self.assertIn(edit_link, content)
        self.assertIn(del_link, content)

    def test_teammate_cannot_see_edit_or_delete_buttons(self):
        """Bob can view Alice's deliverable and open the link, but cannot see edit or delete buttons."""
        self.client.force_login(self.student_b)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Deliverable title and link ARE visible
        self.assertIn("Alice Deliverable", content)
        self.assertIn("https://alice.link/doc", content)
        self.assertIn("Open Link", content)

        # Edit and Delete buttons ARE NOT rendered for Bob
        edit_link = f"/academic/student/deliverable/{self.deliverable_a.pk}/edit/"
        del_link = f"/academic/student/deliverable/{self.deliverable_a.pk}/delete/"
        self.assertNotIn(edit_link, content)
        self.assertNotIn(del_link, content)

    def test_submitter_cannot_see_edit_or_delete_buttons_when_deadline_passed(self):
        """Once the deadline has passed, edit and delete buttons disappear even for Alice."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=1)
        )
        self.client.force_login(self.student_a)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        edit_link = f"/academic/student/deliverable/{self.deliverable_a.pk}/edit/"
        del_link = f"/academic/student/deliverable/{self.deliverable_a.pk}/delete/"
        self.assertNotIn(edit_link, content)
        self.assertNotIn(del_link, content)
        self.assertIn("Alice Deliverable", content)
        self.assertIn("Open Link", content)


# =====================================================================
# 7. COMPLETE MULTI-STEP INTEGRATION LIFECYCLE TESTS
# =====================================================================
class DeliverableCompleteLifecycleIntegrationTests(TestCase):
    """End-to-End integration test across the full student team collaboration lifecycle."""

    def setUp(self):
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_lifecycle@test.com",
            name="Coordinator Life",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_lifecycle@test.com",
            name="Instructor Life",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student1 = User.objects.create_user(
            email="student1_life@test.com",
            name="Student One",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student2 = User.objects.create_user(
            email="student2_life@test.com",
            name="Student Two",
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
            title="Full Lifecycle Project",
            description="Testing entire deliverable lifecycle",
            deadline=timezone.now() + timedelta(days=10)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Lifecycle Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student1)
        TeamMember.objects.create(team=self.team, user=self.student2)

        self.progress_url = f"/academic/student/team/{self.team.team_id}/progress/"

    def test_full_deliverable_submission_workflow_lifecycle(self):
        """
        Tests the complete collaboration lifecycle:
        1. Student 1 loads dashboard and progress -> 0 deliverables.
        2. Student 1 submits Figma Wireframes -> saved and listed.
        3. Student 2 views progress -> sees Figma Wireframes, cannot edit/delete.
        4. Student 2 submits Architecture Spec -> both listed, ordered by newest first.
        5. Student 1 edits Figma Wireframes -> updated.
        6. Student 2 deletes Architecture Spec -> removed.
        7. Project deadline expires -> locked banner, edit/delete/submit blocked.
        """
        # Step 1: Student 1 views initial empty progress
        self.client.force_login(self.student1)
        r = self.client.get(self.progress_url)
        self.assertEqual(r.status_code, 200)
        self.assertIn("No non-coding deliverables have been submitted yet.", r.content.decode())

        # Step 2: Student 1 submits Deliverable 1
        r = self.client.post(self.progress_url, {
            'submit_deliverable': '1',
            'title': 'Figma Wireframes v1',
            'link': 'https://figma.com/file/wireframes-1',
            'description': 'Initial low-fi mockups'
        }, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(NonCodingDeliverable.objects.filter(team=self.team).count(), 1)
        deliv1 = NonCodingDeliverable.objects.get(title='Figma Wireframes v1')
        self.assertEqual(deliv1.submitted_by, self.student1)

        # Step 3: Student 2 logs in, sees Deliverable 1, verifies no edit/delete buttons
        self.client.force_login(self.student2)
        r = self.client.get(self.progress_url)
        content_s2 = r.content.decode()
        self.assertIn("Figma Wireframes v1", content_s2)
        self.assertIn("Student One", content_s2)
        self.assertNotIn(f"/academic/student/deliverable/{deliv1.pk}/edit/", content_s2)
        self.assertNotIn(f"/academic/student/deliverable/{deliv1.pk}/delete/", content_s2)

        # Step 4: Student 2 submits Deliverable 2
        r = self.client.post(self.progress_url, {
            'submit_deliverable': '1',
            'title': 'System Architecture Spec',
            'link': 'https://drive.google.com/file/arch-spec',
            'description': 'Database ERD and class diagrams'
        }, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(NonCodingDeliverable.objects.filter(team=self.team).count(), 2)
        deliv2 = NonCodingDeliverable.objects.get(title='System Architecture Spec')
        self.assertEqual(deliv2.submitted_by, self.student2)

        # Verify ordering: newest (deliv2) should appear first in context
        deliverables_in_order = list(self.team.deliverables.all().order_by('-submitted_at'))
        self.assertEqual(deliverables_in_order[0].pk, deliv2.pk)
        self.assertEqual(deliverables_in_order[1].pk, deliv1.pk)

        # Step 5: Student 1 logs in and edits Deliverable 1
        self.client.force_login(self.student1)
        edit_url = f"/academic/student/deliverable/{deliv1.pk}/edit/"
        r = self.client.post(edit_url, {
            'title': 'Figma Wireframes v2 Final',
            'link': 'https://figma.com/file/wireframes-final',
            'description': 'Approved high-fi prototypes'
        }, follow=True)
        self.assertEqual(r.status_code, 200)
        deliv1.refresh_from_db()
        self.assertEqual(deliv1.title, 'Figma Wireframes v2 Final')

        # Step 6: Student 2 deletes Deliverable 2
        self.client.force_login(self.student2)
        del_url = f"/academic/student/deliverable/{deliv2.pk}/delete/"
        r = self.client.post(del_url, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(NonCodingDeliverable.objects.filter(pk=deliv2.pk).exists())
        self.assertEqual(NonCodingDeliverable.objects.filter(team=self.team).count(), 1)

        # Step 7: Fast-forward deadline to the past
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(minutes=5)
        )
        self.project.refresh_from_db()

        # Both student 1 and student 2 visit page -> form locked
        for student in [self.student1, self.student2]:
            self.client.force_login(student)
            r = self.client.get(self.progress_url)
            self.assertIn("Submissions Locked (Deadline Passed)", r.content.decode())
            self.assertNotIn(f"/academic/student/deliverable/{deliv1.pk}/edit/", r.content.decode())
            self.assertNotIn(f"/academic/student/deliverable/{deliv1.pk}/delete/", r.content.decode())

        # Attempt to edit deliv1 after deadline -> rejected
        self.client.force_login(self.student1)
        r = self.client.post(edit_url, {'title': 'Late Edit', 'link': 'https://figma.com/late'}, follow=True)
        self.assertEqual(r.status_code, 200)
        deliv1.refresh_from_db()
        self.assertEqual(deliv1.title, 'Figma Wireframes v2 Final')

        # Attempt to delete deliv1 after deadline -> rejected
        deliv1_del_url = f"/academic/student/deliverable/{deliv1.pk}/delete/"
        r = self.client.post(deliv1_del_url, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(NonCodingDeliverable.objects.filter(pk=deliv1.pk).exists())


# =====================================================================
# 8. LIVE SELENIUM E2E BROWSER WORKFLOW TESTS
# =====================================================================
class DeliverableSeleniumE2EWorkflowTests(StaticLiveServerTestCase):
    """End-to-end browser tests verifying UI form submission, rendering, editing, and deletion."""

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
            email="coord_e2e@test.com",
            name="Coordinator E2E",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_e2e@test.com",
            name="Instructor E2E",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student = User.objects.create_user(
            email="student_e2e@test.com",
            name="Alice Student",
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
            title="E2E Browser Project",
            description="Testing live UI deliverable workflow",
            deadline=timezone.now() + timedelta(days=10)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Browser Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student)

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

    def test_complete_deliverable_e2e_browser_workflow(self):
        """
        E2E Browser Test:
        1. Login as student.
        2. Navigate to student dashboard -> click 'View Team Progress Analytics'.
        3. Fill out Submit Deliverable form (Title, Link, Description).
        4. Click 'Submit Deliverable'.
        5. Verify deliverable appears in 'Submitted Deliverables' list.
        6. Click 'Edit' button -> verify pre-populated form.
        7. Change title and save changes.
        8. Verify updated title appears in list.
        9. Click 'Delete' button -> arrive at confirmation page.
        10. Click 'Yes, Delete It' -> deliverable removed, empty state shown.
        """
        self._login("student_e2e@test.com", "password123")

        # Navigate to Dashboard
        self.driver.get(f"{self.live_server_url}/academic/student/dashboard/")
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        # Click "View Team Progress Analytics" button
        progress_btn = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'View Team Progress Analytics')]"))
        )
        progress_btn.click()

        # Verify on Progress page
        self.wait.until(lambda d: f"/academic/student/team/{self.team.team_id}/progress/" in d.current_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h3[contains(text(), 'Submit Deliverable')]")))

        # Verify initial empty state
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("No non-coding deliverables have been submitted yet", body_text)

        # Fill Deliverable Form
        title_input = self.driver.find_element(By.NAME, "title")
        link_input = self.driver.find_element(By.NAME, "link")
        desc_input = self.driver.find_element(By.NAME, "description")

        title_input.send_keys("Figma Prototype E2E")
        link_input.send_keys("https://www.figma.com/design/test-prototype")
        desc_input.send_keys("Interactive mockups and design system components.")

        submit_deliverable_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Submit Deliverable')]")
        submit_deliverable_btn.click()

        # Wait for page reload and success message
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Deliverable submitted successfully.')]")))

        # Verify item in list
        item_heading = self.wait.until(EC.presence_of_element_located((By.XPATH, "//h4[contains(text(), 'Figma Prototype E2E')]")))
        self.assertTrue(item_heading.is_displayed())
        page_content = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Alice Student", page_content)
        self.assertIn("1 Items", page_content)

        # Click Edit Button
        edit_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//a[@title='Edit']")))
        edit_btn.click()

        # Verify on Edit Deliverable page
        self.wait.until(lambda d: "/edit/" in d.current_url)
        edit_title_input = self.wait.until(EC.presence_of_element_located((By.NAME, "title")))
        self.assertEqual(edit_title_input.get_attribute("value"), "Figma Prototype E2E")

        # Update title
        edit_title_input.clear()
        edit_title_input.send_keys("Figma Prototype E2E (v2 Approved)")

        save_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Save Changes')]")
        save_btn.click()

        # Wait for redirect back to progress page
        self.wait.until(lambda d: f"/academic/student/team/{self.team.team_id}/progress/" in d.current_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Successfully updated')]")))

        # Verify updated title in list
        updated_heading = self.wait.until(EC.presence_of_element_located((By.XPATH, "//h4[contains(text(), 'Figma Prototype E2E (v2 Approved)')]")))
        self.assertTrue(updated_heading.is_displayed())

        # Click Delete Button
        delete_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//a[@title='Delete']")))
        delete_btn.click()

        # Verify on Delete Deliverable confirmation page
        self.wait.until(lambda d: "/delete/" in d.current_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(text(), 'Delete Deliverable?')]")))

        confirm_del_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Yes, Delete It')]")))
        confirm_del_btn.click()

        # Wait for redirect back to progress page
        self.wait.until(lambda d: f"/academic/student/team/{self.team.team_id}/progress/" in d.current_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Deliverable successfully removed.')]")))

        # Verify empty state is displayed again
        final_body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("No non-coding deliverables have been submitted yet", final_body_text)
        self.assertIn("0 Items", final_body_text)

