import os
import sys
from datetime import timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.test import TestCase, override_settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from accounts.models import User
from academic.models import Course, CourseSection, Project, CourseAssessmentPolicy, PolicyChangeRequest


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class StandardizedAndProjectPoliciesUnitTests(TestCase):
    """
    Unit tests for standardized and project-specific policies.
    Acceptance criteria: Tests verify policy creation, update, retrieval,
    and project-specific configuration.
    """

    def setUp(self):
        super().setUp()
        self.coordinator = User.objects.create_user(
            email="coord_policy@example.com",
            name="Coordinator Policy",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_policy@example.com",
            name="Instructor Policy",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE302",
            course_name="Database Systems",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.project_deadline = timezone.now() + timedelta(days=14)
        self.project = Project.objects.create(
            section=self.section,
            title="Database Project",
            deadline=self.project_deadline,
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )

    def test_01_create_standard_course_policy(self):
        """Standard CourseAssessmentPolicy is created with valid weights and linked to course."""
        policy = CourseAssessmentPolicy.objects.create(
            course=self.course,
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        policy.clean()
        self.assertEqual(policy.course, self.course)
        self.assertEqual(str(policy), f"Policy for {self.course.course_code}")
        self.assertEqual(self.course.assessment_policy, policy)

    def test_02_update_and_retrieve_course_policy(self):
        """Updating course policy persists correctly and is retrievable."""
        policy = CourseAssessmentPolicy.objects.create(
            course=self.course,
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        policy.weight_github = 50
        policy.weight_deliverables = 25
        policy.weight_peer = 25
        policy.clean()
        policy.save()

        retrieved = CourseAssessmentPolicy.objects.get(course=self.course)
        self.assertEqual(retrieved.weight_github, 50)
        self.assertEqual(retrieved.weight_deliverables, 25)
        self.assertEqual(retrieved.weight_peer, 25)

    def test_03_standard_policy_clean_validation(self):
        """CourseAssessmentPolicy.clean() enforces exact 100% total weight."""
        policy = CourseAssessmentPolicy(
            course=self.course,
            weight_github=50,
            weight_deliverables=40,
            weight_peer=20  # total = 110%
        )
        with self.assertRaises(ValidationError) as ctx:
            policy.clean()
        self.assertIn("100%", str(ctx.exception))

    def test_04_create_and_retrieve_project_policy_request(self):
        """PolicyChangeRequest for project-specific policy is created with pending status."""
        request = PolicyChangeRequest.objects.create(
            project=self.project,
            instructor=self.instructor,
            proposed_github=60,
            proposed_deliverables=20,
            proposed_peer=20,
            justification="Focus on code implementation"
        )
        request.clean()
        self.assertEqual(request.status, 'PENDING')
        self.assertEqual(self.project.policy_requests.count(), 1)
        self.assertEqual(self.project.policy_requests.first(), request)

    def test_05_project_policy_request_clean_validation(self):
        """PolicyChangeRequest.clean() rejects proposed weights not summing to 100%."""
        request = PolicyChangeRequest(
            project=self.project,
            instructor=self.instructor,
            proposed_github=40,
            proposed_deliverables=30,
            proposed_peer=20,  # total = 90%
            justification="Invalid weights"
        )
        with self.assertRaises(ValidationError) as ctx:
            request.clean()
        self.assertIn("100%", str(ctx.exception))

    def test_06_project_specific_configuration_independence(self):
        """Project-specific configurations remain isolated between projects."""
        section_b = CourseSection.objects.create(
            course=self.course,
            section_name="Section B",
            instructor=self.instructor
        )
        project_b = Project.objects.create(
            section=section_b,
            title="Project B",
            deadline=self.project_deadline,
            weight_github=50,
            weight_deliverables=25,
            weight_peer=25
        )
        # Modify Project A's weights
        self.project.weight_github = 34
        self.project.weight_deliverables = 33
        self.project.weight_peer = 33
        self.project.save()

        # Project B retains its own settings
        project_b.refresh_from_db()
        self.assertEqual(project_b.weight_github, 50)
        self.assertEqual(project_b.weight_deliverables, 25)
        self.assertEqual(project_b.weight_peer, 25)
