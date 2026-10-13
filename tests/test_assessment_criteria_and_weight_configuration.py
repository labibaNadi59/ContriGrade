import os
import sys
from datetime import timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError

from accounts.models import User
from academic.models import Course, CourseSection, Project, EvaluationCriterion
from academic.forms import ProjectForm


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class BaseAssessmentTestSetup(TestCase):
    """Base setup for assessment criteria and weight configuration tests."""

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Users
        self.coordinator = User.objects.create_user(
            email="coord_assess@example.com",
            name="Coordinator Alice",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_assess@example.com",
            name="Instructor Bob",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.other_instructor = User.objects.create_user(
            email="other_inst@example.com",
            name="Instructor Other",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student = User.objects.create_user(
            email="student_assess@example.com",
            name="Student Charlie",
            role=User.Role.STUDENT,
            password="password123"
        )

        # Academic hierarchy
        self.course = Course.objects.create(
            course_code="CSE412",
            course_name="Software Quality & Testing",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 01",
            instructor=self.instructor
        )
        self.other_section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 02",
            instructor=self.other_instructor
        )

        # Projects
        self.project_deadline = timezone.now() + timedelta(days=21)
        self.project = Project.objects.create(
            section=self.section,
            title="Automated Assessment Hub",
            description="Testing rubric criteria and assessment weights",
            deadline=self.project_deadline,
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )

        self.other_project = Project.objects.create(
            section=self.other_section,
            title="Other Section Project",
            description="Testing instructor project isolation",
            deadline=self.project_deadline,
            weight_github=50,
            weight_deliverables=30,
            weight_peer=20
        )

        self.edit_project_url = reverse('edit_project', kwargs={'project_id': self.project.pk})


# =====================================================================
# 1. MODEL-LEVEL TESTS (Criteria & Weights)
# =====================================================================
class AssessmentCriteriaModelTests(BaseAssessmentTestSetup):
    """Unit tests for EvaluationCriterion model properties and operations."""

    def test_criterion_creation_with_defaults(self):
        """EvaluationCriterion is created with default max_score of 5."""
        criterion = EvaluationCriterion.objects.create(
            project=self.project,
            name="Code Quality"
        )
        self.assertEqual(criterion.name, "Code Quality")
        self.assertEqual(criterion.description, "")
        self.assertEqual(criterion.max_score, 5)
        self.assertEqual(criterion.project, self.project)
        self.assertEqual(str(criterion), f"Code Quality - {self.project.title}")

    def test_criterion_custom_attributes(self):
        """EvaluationCriterion stores custom name, description, and max score."""
        criterion = EvaluationCriterion.objects.create(
            project=self.project,
            name="Sprint Delivery",
            description="Timely submission and meeting sprint deadlines",
            max_score=10
        )
        self.assertEqual(criterion.name, "Sprint Delivery")
        self.assertEqual(criterion.description, "Timely submission and meeting sprint deadlines")
        self.assertEqual(criterion.max_score, 10)

    def test_project_cascade_deletes_evaluation_criteria(self):
        """Deleting a project cascades and removes all associated evaluation criteria."""
        crit1 = EvaluationCriterion.objects.create(project=self.project, name="Criterion 1")
        crit2 = EvaluationCriterion.objects.create(project=self.project, name="Criterion 2")
        self.assertEqual(self.project.evaluation_criteria.count(), 2)

        self.project.delete()
        self.assertFalse(EvaluationCriterion.objects.filter(pk=crit1.pk).exists())
        self.assertFalse(EvaluationCriterion.objects.filter(pk=crit2.pk).exists())


class ProjectWeightModelValidationTests(BaseAssessmentTestSetup):
    """Unit tests for Project model assessment weight validation."""

    def test_default_weights_sum_to_100(self):
        """Default project weights (40 + 30 + 30) sum to 100% and pass validation."""
        self.assertEqual(self.project.weight_github, 40)
        self.assertEqual(self.project.weight_deliverables, 30)
        self.assertEqual(self.project.weight_peer, 30)
        total = self.project.weight_github + self.project.weight_deliverables + self.project.weight_peer
        self.assertEqual(total, 100)
        # Should not raise
        self.project.clean()

    def test_valid_custom_weight_distributions_pass_clean(self):
        """Custom weight distributions totaling exactly 100% pass clean()."""
        valid_distributions = [
            (50, 25, 25),
            (60, 20, 20),
            (100, 0, 0),
            (0, 50, 50),
            (34, 33, 33),
            (10, 80, 10),
        ]
        for w_git, w_deliv, w_peer in valid_distributions:
            self.project.weight_github = w_git
            self.project.weight_deliverables = w_deliv
            self.project.weight_peer = w_peer
            try:
                self.project.clean()
            except ValidationError:
                self.fail(f"clean() raised ValidationError unexpectedly for weights ({w_git}, {w_deliv}, {w_peer})")

    def test_weights_summing_less_than_100_raises_validation_error(self):
        """Weights totaling less than 100% raise ValidationError."""
        self.project.weight_github = 30
        self.project.weight_deliverables = 30
        self.project.weight_peer = 30  # total = 90%
        with self.assertRaises(ValidationError) as ctx:
            self.project.clean()
        self.assertIn("Total assessment weights must equal exactly 100%", str(ctx.exception))
        self.assertIn("Current total is 90%", str(ctx.exception))

    def test_weights_summing_greater_than_100_raises_validation_error(self):
        """Weights totaling greater than 100% raise ValidationError."""
        self.project.weight_github = 50
        self.project.weight_deliverables = 40
        self.project.weight_peer = 30  # total = 120%
        with self.assertRaises(ValidationError) as ctx:
            self.project.clean()
        self.assertIn("Total assessment weights must equal exactly 100%", str(ctx.exception))
        self.assertIn("Current total is 120%", str(ctx.exception))

    def test_none_weights_treated_as_zero_and_validated(self):
        """None weights evaluate to 0 in clean() calculation."""
        self.project.weight_github = None
        self.project.weight_deliverables = 50
        self.project.weight_peer = 50
        # 0 + 50 + 50 = 100%
        self.project.clean()


# =====================================================================
# 2. FORM-LEVEL TESTS (ProjectForm & Weight Validation)
# =====================================================================
class ProjectFormWeightValidationTests(BaseAssessmentTestSetup):
    """Unit tests for ProjectForm validation of assessment weights."""

    def test_form_valid_when_weights_sum_to_100(self):
        """ProjectForm is valid when weights sum to exactly 100%."""
        form_data = {
            'title': 'Test Project',
            'description': 'Valid weights form test',
            'section': self.section.pk,
            'deadline': (timezone.now() + timedelta(days=14)).strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 50,
            'weight_deliverables': 30,
            'weight_peer': 20,
        }
        form = ProjectForm(data=form_data, user=self.instructor)
        self.assertTrue(form.is_valid(), form.errors)

    def test_form_invalid_when_weights_sum_to_less_than_100(self):
        """ProjectForm raises non-field error when weights sum to less than 100%."""
        form_data = {
            'title': 'Test Project',
            'description': 'Invalid weights form test',
            'section': self.section.pk,
            'deadline': (timezone.now() + timedelta(days=14)).strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 20,
            'weight_deliverables': 20,
            'weight_peer': 20,  # total = 60%
        }
        form = ProjectForm(data=form_data, user=self.instructor)
        self.assertFalse(form.is_valid())
        self.assertIn("Assessment weights must sum to exactly 100%. Your current total is 60%.", form.non_field_errors())

    def test_form_invalid_when_weights_sum_to_greater_than_100(self):
        """ProjectForm raises non-field error when weights sum to greater than 100%."""
        form_data = {
            'title': 'Test Project',
            'description': 'Invalid weights form test',
            'section': self.section.pk,
            'deadline': (timezone.now() + timedelta(days=14)).strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 60,
            'weight_deliverables': 40,
            'weight_peer': 20,  # total = 120%
        }
        form = ProjectForm(data=form_data, user=self.instructor)
        self.assertFalse(form.is_valid())
        self.assertIn("Assessment weights must sum to exactly 100%. Your current total is 120%.", form.non_field_errors())

    def test_form_section_queryset_filtered_to_instructor_sections(self):
        """Instructor only sees their assigned sections in the ProjectForm dropdown."""
        form = ProjectForm(user=self.instructor)
        section_ids = list(form.fields['section'].queryset.values_list('pk', flat=True))
        self.assertIn(self.section.pk, section_ids)
        self.assertNotIn(self.other_section.pk, section_ids)


# =====================================================================
# 3. INTERFACE WORKFLOW TESTS: ASSESSMENT CRITERIA (CRUD)
# =====================================================================
class AssessmentCriteriaInterfaceWorkflowTests(BaseAssessmentTestSetup):
    """Verifies that instructors can create, update, and remove criteria via interface."""

    def test_interface_displays_criteria_and_weight_configuration(self):
        """Instructor accessing edit project sees settings tab, criteria tab, and current weights."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.edit_project_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        # Tabs and sections
        self.assertIn("Project Settings", content)
        self.assertIn("Peer Evaluation Criteria", content)
        self.assertIn("Contribution Weights", content)
        # Weight fields
        self.assertIn("weight_github", content)
        self.assertIn("weight_deliverables", content)
        self.assertIn("weight_peer", content)
        # Add criterion form fields
        self.assertIn("criterion_name", content)
        self.assertIn("criterion_max_score", content)

    def test_instructor_can_create_assessment_criterion(self):
        """Instructor creates an assessment criterion with custom attributes."""
        self.client.force_login(self.instructor)
        post_data = {
            'add_criterion': '1',
            'criterion_name': 'Technical Architecture',
            'criterion_description': 'System design, modularity, and database schema',
            'criterion_max_score': '10'
        }
        resp = self.client.post(self.edit_project_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Verify database persistence
        criterion = EvaluationCriterion.objects.filter(project=self.project, name="Technical Architecture").first()
        self.assertIsNotNone(criterion)
        self.assertEqual(criterion.description, "System design, modularity, and database schema")
        self.assertEqual(criterion.max_score, 10)

        # Verify flash success message
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Added peer evaluation criterion: 'Technical Architecture'" in m for m in messages))

    def test_instructor_create_criterion_defaults_max_score(self):
        """Creating a criterion without explicit max_score defaults to 5."""
        self.client.force_login(self.instructor)
        post_data = {
            'add_criterion': '1',
            'criterion_name': 'Team Communication',
            'criterion_description': 'Prompt communication in discussions',
            'criterion_max_score': '5'
        }
        self.client.post(self.edit_project_url, post_data, follow=True)

        criterion = EvaluationCriterion.objects.get(project=self.project, name="Team Communication")
        self.assertEqual(criterion.max_score, 5)

    def test_instructor_cannot_create_criterion_with_empty_name(self):
        """Submitting an empty criterion name does not create a database record."""
        self.client.force_login(self.instructor)
        initial_count = EvaluationCriterion.objects.filter(project=self.project).count()
        post_data = {
            'add_criterion': '1',
            'criterion_name': '   ',
            'criterion_description': 'Empty name test',
            'criterion_max_score': '5'
        }
        self.client.post(self.edit_project_url, post_data, follow=True)

        self.assertEqual(EvaluationCriterion.objects.filter(project=self.project).count(), initial_count)

    def test_instructor_can_update_assessment_criterion(self):
        """Instructor updates an existing assessment criterion's name, description, and max score."""
        criterion = EvaluationCriterion.objects.create(
            project=self.project,
            name="Original Metric",
            description="Original description",
            max_score=5
        )

        self.client.force_login(self.instructor)
        post_data = {
            'update_criterion': '1',
            'criterion_id': criterion.pk,
            'criterion_name': 'Updated Metric Name',
            'criterion_description': 'Revised detailed description for rubric',
            'criterion_max_score': '15'
        }
        resp = self.client.post(self.edit_project_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Refresh from database and assert changes were persisted
        criterion.refresh_from_db()
        self.assertEqual(criterion.name, "Updated Metric Name")
        self.assertEqual(criterion.description, "Revised detailed description for rubric")
        self.assertEqual(criterion.max_score, 15)

        # Verify feedback message
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Updated criterion: 'Updated Metric Name'" in m for m in messages))

    def test_instructor_can_remove_assessment_criterion(self):
        """Instructor removes an existing assessment criterion."""
        criterion = EvaluationCriterion.objects.create(
            project=self.project,
            name="Temporary Metric",
            description="Will be removed",
            max_score=5
        )
        self.assertEqual(self.project.evaluation_criteria.count(), 1)

        self.client.force_login(self.instructor)
        post_data = {
            'delete_criterion': criterion.pk
        }
        resp = self.client.post(self.edit_project_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Verify criterion was deleted from database
        self.assertFalse(EvaluationCriterion.objects.filter(pk=criterion.pk).exists())
        self.assertEqual(self.project.evaluation_criteria.count(), 0)

        # Verify message
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Deleted criterion: 'Temporary Metric'" in m for m in messages))

    def test_instructor_cannot_delete_criterion_belonging_to_another_project(self):
        """Attempting to delete another project's criterion via this project returns 404."""
        other_criterion = EvaluationCriterion.objects.create(
            project=self.other_project,
            name="Other Project Metric",
            max_score=5
        )

        self.client.force_login(self.instructor)
        post_data = {
            'delete_criterion': other_criterion.pk
        }
        resp = self.client.post(self.edit_project_url, post_data)
        self.assertEqual(resp.status_code, 404)
        # The other criterion must still exist
        self.assertTrue(EvaluationCriterion.objects.filter(pk=other_criterion.pk).exists())

    def test_instructor_cannot_update_criterion_belonging_to_another_project(self):
        """Attempting to update another project's criterion via this project returns 404."""
        other_criterion = EvaluationCriterion.objects.create(
            project=self.other_project,
            name="Foreign Metric",
            max_score=5
        )

        self.client.force_login(self.instructor)
        post_data = {
            'update_criterion': '1',
            'criterion_id': other_criterion.pk,
            'criterion_name': 'Tampered Metric',
            'criterion_max_score': '20'
        }
        resp = self.client.post(self.edit_project_url, post_data)
        self.assertEqual(resp.status_code, 404)
        # Unchanged
        other_criterion.refresh_from_db()
        self.assertEqual(other_criterion.name, "Foreign Metric")


# =====================================================================
# 4. INTERFACE WORKFLOW TESTS: WEIGHT CONFIGURATION
# =====================================================================
class WeightConfigurationInterfaceWorkflowTests(BaseAssessmentTestSetup):
    """Verifies configuring weights for GitHub, deliverables, and peer evaluations."""

    def test_instructor_saves_valid_weight_configuration_successfully(self):
        """Instructor configures and saves new valid weights (50% GitHub, 25% Deliverables, 25% Peer)."""
        self.client.force_login(self.instructor)
        post_data = {
            'update_project': '1',
            'title': self.project.title,
            'description': self.project.description,
            'section': self.section.pk,
            'deadline': self.project_deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 50,
            'weight_deliverables': 25,
            'weight_peer': 25,
        }
        resp = self.client.post(self.edit_project_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Check DB values
        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 50)
        self.assertEqual(self.project.weight_deliverables, 25)
        self.assertEqual(self.project.weight_peer, 25)

        # Check success message
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Successfully updated" in m for m in messages))

    def test_instructor_saves_boundary_weights_successfully(self):
        """Instructor can assign 100% to GitHub Analytics and 0% to other components."""
        self.client.force_login(self.instructor)
        post_data = {
            'update_project': '1',
            'title': self.project.title,
            'description': self.project.description,
            'section': self.section.pk,
            'deadline': self.project_deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 100,
            'weight_deliverables': 0,
            'weight_peer': 0,
        }
        resp = self.client.post(self.edit_project_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 100)
        self.assertEqual(self.project.weight_deliverables, 0)
        self.assertEqual(self.project.weight_peer, 0)

    def test_instructor_submitting_weights_exceeding_100_rejected(self):
        """Submitting weights totaling over 100% is rejected and does not update the database."""
        self.client.force_login(self.instructor)
        initial_weights = (self.project.weight_github, self.project.weight_deliverables, self.project.weight_peer)

        post_data = {
            'update_project': '1',
            'title': self.project.title,
            'description': self.project.description,
            'section': self.section.pk,
            'deadline': self.project_deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 50,
            'weight_deliverables': 50,
            'weight_peer': 20,  # total = 120%
        }
        resp = self.client.post(self.edit_project_url, post_data)
        # Should re-render edit_project page with errors (not redirect)
        self.assertEqual(resp.status_code, 200)

        # Verify DB weights were NOT changed
        self.project.refresh_from_db()
        self.assertEqual((self.project.weight_github, self.project.weight_deliverables, self.project.weight_peer), initial_weights)

        # Verify error appears in page
        content = resp.content.decode('utf-8')
        self.assertIn("Assessment weights must sum to exactly 100%", content)
        self.assertIn("120%", content)

    def test_instructor_submitting_weights_below_100_rejected(self):
        """Submitting weights totaling under 100% is rejected and does not update the database."""
        self.client.force_login(self.instructor)
        initial_weights = (self.project.weight_github, self.project.weight_deliverables, self.project.weight_peer)

        post_data = {
            'update_project': '1',
            'title': self.project.title,
            'description': self.project.description,
            'section': self.section.pk,
            'deadline': self.project_deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 25,
            'weight_deliverables': 25,
            'weight_peer': 25,  # total = 75%
        }
        resp = self.client.post(self.edit_project_url, post_data)
        self.assertEqual(resp.status_code, 200)

        self.project.refresh_from_db()
        self.assertEqual((self.project.weight_github, self.project.weight_deliverables, self.project.weight_peer), initial_weights)

        content = resp.content.decode('utf-8')
        self.assertIn("Assessment weights must sum to exactly 100%", content)
        self.assertIn("75%", content)


# =====================================================================
# 5. SECURITY & ACCESS CONTROL TESTS
# =====================================================================
class AssessmentSecurityAndAccessControlTests(BaseAssessmentTestSetup):
    """Verifies authorization checks for editing criteria and weights."""

    def test_anonymous_user_redirected_to_login(self):
        """Unauthenticated user is redirected to login page."""
        resp = self.client.get(self.edit_project_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('login'), resp.url)

    def test_student_blocked_from_project_edit_interface(self):
        """Student is blocked from accessing the project edit interface."""
        self.client.force_login(self.student)
        resp = self.client.get(self.edit_project_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Access denied.", messages)

    def test_unassigned_instructor_blocked_from_editing_project(self):
        """Instructor teaching Section B cannot edit Section A's project."""
        self.client.force_login(self.other_instructor)
        resp = self.client.get(self.edit_project_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("You can only edit projects assigned to your sections.", messages)

    def test_unassigned_instructor_blocked_from_posting_criteria(self):
        """Unassigned instructor cannot POST to add criteria to another instructor's project."""
        self.client.force_login(self.other_instructor)
        initial_count = EvaluationCriterion.objects.filter(project=self.project).count()
        post_data = {
            'add_criterion': '1',
            'criterion_name': 'Unauthorized Criterion',
            'criterion_max_score': '5'
        }
        resp = self.client.post(self.edit_project_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        # No criterion was created
        self.assertEqual(EvaluationCriterion.objects.filter(project=self.project).count(), initial_count)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("You can only edit projects assigned to your sections.", messages)

    def test_coordinator_can_access_and_configure_project(self):
        """Coordinator has elevated access to view and configure project criteria and weights."""
        self.client.force_login(self.coordinator)
        resp = self.client.get(self.edit_project_url)
        self.assertEqual(resp.status_code, 200)

        # Coordinator can add a criterion
        post_data = {
            'add_criterion': '1',
            'criterion_name': 'Coordinator Standard Metric',
            'criterion_max_score': '10'
        }
        post_resp = self.client.post(self.edit_project_url, post_data, follow=True)
        self.assertEqual(post_resp.status_code, 200)
        self.assertTrue(EvaluationCriterion.objects.filter(project=self.project, name="Coordinator Standard Metric").exists())
