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
class ProjectAssessmentConfigurationWorkflowIntegrationTests(TestCase):
    """
    Integration tests for project assessment configuration workflow.
    Acceptance criteria: Complete criteria and weight configuration workflow
    works correctly for a project.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_workflow@example.com",
            name="Coordinator Workflow",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_workflow@example.com",
            name="Instructor Workflow",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE301",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 01",
            instructor=self.instructor
        )
        self.project_deadline = timezone.now() + timedelta(days=14)
        self.project = Project.objects.create(
            section=self.section,
            title="Assessment Workflow Project",
            description="Testing assessment criteria and weight configuration",
            deadline=self.project_deadline,
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        self.edit_url = reverse('edit_project', kwargs={'project_id': self.project.pk})
        self.client.force_login(self.instructor)

    def test_01_view_configuration_page(self):
        """Instructor successfully accesses the configuration interface with existing weights."""
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Peer Evaluation Criteria", content)
        self.assertIn("Contribution Weights", content)
        self.assertEqual(resp.context['project'].weight_github, 40)

    def test_02_add_evaluation_criterion_workflow(self):
        """Instructor adds a new evaluation criterion with name and max score."""
        post_data = {
            'add_criterion': '1',
            'criterion_name': 'Code Review Quality',
            'criterion_description': 'PR reviews and comments',
            'criterion_max_score': '10'
        }
        resp = self.client.post(self.edit_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        criterion = EvaluationCriterion.objects.filter(project=self.project, name='Code Review Quality').first()
        self.assertIsNotNone(criterion)
        self.assertEqual(criterion.max_score, 10)
        self.assertEqual(criterion.description, 'PR reviews and comments')

    def test_03_update_evaluation_criterion_workflow(self):
        """Instructor modifies an existing evaluation criterion."""
        criterion = EvaluationCriterion.objects.create(
            project=self.project,
            name="Initial Rubric",
            description="Initial description",
            max_score=5
        )
        post_data = {
            'update_criterion': '1',
            'criterion_id': criterion.pk,
            'criterion_name': 'Updated Rubric Metric',
            'criterion_description': 'Revised rubric description',
            'criterion_max_score': '15'
        }
        resp = self.client.post(self.edit_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        criterion.refresh_from_db()
        self.assertEqual(criterion.name, 'Updated Rubric Metric')
        self.assertEqual(criterion.max_score, 15)

    def test_04_configure_project_weights_workflow(self):
        """Instructor updates component assessment weights totaling 100%."""
        post_data = {
            'update_project': '1',
            'title': self.project.title,
            'description': self.project.description,
            'section': self.section.pk,
            'deadline': self.project_deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 50,
            'weight_deliverables': 25,
            'weight_peer': 25
        }
        resp = self.client.post(self.edit_url, post_data)
        self.assertEqual(resp.status_code, 302)

        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 50)
        self.assertEqual(self.project.weight_deliverables, 25)
        self.assertEqual(self.project.weight_peer, 25)

    def test_05_delete_evaluation_criterion_workflow(self):
        """Instructor removes an existing evaluation criterion."""
        criterion = EvaluationCriterion.objects.create(
            project=self.project,
            name="Obsolete Metric",
            max_score=5
        )
        post_data = {'delete_criterion': criterion.pk}
        resp = self.client.post(self.edit_url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(EvaluationCriterion.objects.filter(pk=criterion.pk).exists())

    def test_06_complete_criteria_and_weight_workflow(self):
        """Complete workflow: add criteria, update weights, and verify configured state."""
        # 1. Add criterion
        self.client.post(self.edit_url, {
            'add_criterion': '1',
            'criterion_name': 'Teamwork',
            'criterion_description': 'Collaboration skills',
            'criterion_max_score': '10'
        })
        # 2. Update weights to 60/20/20
        self.client.post(self.edit_url, {
            'update_project': '1',
            'title': self.project.title,
            'description': self.project.description,
            'section': self.section.pk,
            'deadline': self.project_deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 60,
            'weight_deliverables': 20,
            'weight_peer': 20
        })
        # 3. Verify complete configuration
        resp = self.client.get(self.edit_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.project.evaluation_criteria.count(), 1)
        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 60)
        self.assertEqual(self.project.weight_deliverables, 20)
        self.assertEqual(self.project.weight_peer, 20)
