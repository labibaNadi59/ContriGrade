import os
import sys
from datetime import timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from academic.models import Course, CourseSection, Project, EvaluationCriterion


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AssessmentConfigurationValidationAndPersistenceIntegrationTests(TestCase):
    """
    Integration tests for assessment configuration validation and persistence.
    Acceptance criteria: Only valid configurations can be saved and the saved
    configuration is correctly retrieved for the project.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_persist@example.com",
            name="Coordinator Persist",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_persist@example.com",
            name="Instructor Persist",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE306",
            course_name="Software Architecture",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 01",
            instructor=self.instructor
        )
        self.deadline = timezone.now() + timedelta(days=21)
        self.project = Project.objects.create(
            section=self.section,
            title="Architecture Assessment",
            deadline=self.deadline,
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        self.edit_url = reverse('edit_project', kwargs={'project_id': self.project.pk})
        self.client.force_login(self.instructor)

    def test_01_valid_weight_configuration_saved_and_retrieved(self):
        """Valid weight configuration is persisted to DB and retrieved in project view."""
        post_data = {
            'update_project': '1',
            'title': self.project.title,
            'description': self.project.description,
            'section': self.section.pk,
            'deadline': self.deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 45,
            'weight_deliverables': 35,
            'weight_peer': 20
        }
        resp = self.client.post(self.edit_url, post_data)
        self.assertEqual(resp.status_code, 302)

        # Retrieve and verify persistence
        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 45)
        self.assertEqual(self.project.weight_deliverables, 35)
        self.assertEqual(self.project.weight_peer, 20)

        # Retrieve via GET request
        get_resp = self.client.get(self.edit_url)
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.context['project'].weight_github, 45)

    def test_02_invalid_weight_configuration_rejected_and_not_saved(self):
        """Invalid weight configuration is rejected and initial values are preserved."""
        initial_weights = (self.project.weight_github, self.project.weight_deliverables, self.project.weight_peer)
        post_data = {
            'update_project': '1',
            'title': self.project.title,
            'description': self.project.description,
            'section': self.section.pk,
            'deadline': self.deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 50,
            'weight_deliverables': 50,
            'weight_peer': 20  # total = 120%
        }
        resp = self.client.post(self.edit_url, post_data)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Assessment weights must sum to exactly 100%", resp.content.decode('utf-8'))

        # DB values must remain unchanged
        self.project.refresh_from_db()
        self.assertEqual(
            (self.project.weight_github, self.project.weight_deliverables, self.project.weight_peer),
            initial_weights
        )

    def test_03_valid_criterion_saved_and_retrieved(self):
        """Valid evaluation criterion is saved to database and retrieved in project criteria list."""
        resp = self.client.post(self.edit_url, {
            'add_criterion': '1',
            'criterion_name': 'Design Patterns Usage',
            'criterion_description': 'Proper use of GoF patterns',
            'criterion_max_score': '10'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        criterion = EvaluationCriterion.objects.filter(project=self.project, name='Design Patterns Usage').first()
        self.assertIsNotNone(criterion)
        self.assertEqual(criterion.max_score, 10)

        # Retrieved in view context
        get_resp = self.client.get(self.edit_url)
        self.assertIn(criterion, get_resp.context['criteria'])

    def test_04_invalid_criterion_rejected_and_not_saved(self):
        """Empty criterion name is rejected and not saved to database."""
        initial_count = self.project.evaluation_criteria.count()
        resp = self.client.post(self.edit_url, {
            'add_criterion': '1',
            'criterion_name': '   ',
            'criterion_description': 'Blank name',
            'criterion_max_score': '5'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.project.evaluation_criteria.count(), initial_count)
        self.assertIn("Criterion name cannot be empty.", resp.content.decode('utf-8'))

    def test_05_criterion_update_persistence(self):
        """Updated criterion changes are saved and persist upon subsequent retrieval."""
        criterion = EvaluationCriterion.objects.create(
            project=self.project,
            name="Original Standard",
            max_score=5
        )
        resp = self.client.post(self.edit_url, {
            'update_criterion': '1',
            'criterion_id': criterion.pk,
            'criterion_name': 'Persisted Updated Standard',
            'criterion_description': 'Updated description',
            'criterion_max_score': '12'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)

        criterion.refresh_from_db()
        self.assertEqual(criterion.name, 'Persisted Updated Standard')
        self.assertEqual(criterion.max_score, 12)

    def test_06_comprehensive_saved_configuration_retrieval(self):
        """Full configuration (weights + multiple criteria) is persisted and correctly retrievable."""
        # 1. Add 2 criteria
        EvaluationCriterion.objects.create(project=self.project, name="Rubric Alpha", max_score=10)
        EvaluationCriterion.objects.create(project=self.project, name="Rubric Beta", max_score=15)

        # 2. Update weights to 35/35/30
        self.client.post(self.edit_url, {
            'update_project': '1',
            'title': self.project.title,
            'description': self.project.description,
            'section': self.section.pk,
            'deadline': self.deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 35,
            'weight_deliverables': 35,
            'weight_peer': 30
        })

        # 3. Retrieve configuration
        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 35)
        self.assertEqual(self.project.weight_deliverables, 35)
        self.assertEqual(self.project.weight_peer, 30)

        criteria_names = list(self.project.evaluation_criteria.values_list('name', flat=True))
        self.assertIn("Rubric Alpha", criteria_names)
        self.assertIn("Rubric Beta", criteria_names)
