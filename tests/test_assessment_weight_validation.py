import os
import sys
from datetime import timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.test import TestCase, override_settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from accounts.models import User
from academic.models import Course, CourseSection, Project, CourseAssessmentPolicy
from academic.forms import ProjectForm


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AssessmentWeightValidationUnitTests(TestCase):
    """
    Unit tests for assessment weight validation.
    Acceptance criteria: Tests cover valid weights, invalid values,
    missing weights, and incorrect total weights.
    """

    def setUp(self):
        super().setUp()
        self.coordinator = User.objects.create_user(
            email="coord_val@example.com",
            name="Coordinator Validation",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_val@example.com",
            name="Instructor Validation",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE305",
            course_name="Software Testing",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 01",
            instructor=self.instructor
        )
        self.deadline = timezone.now() + timedelta(days=14)
        self.project = Project.objects.create(
            section=self.section,
            title="Validation Project",
            deadline=self.deadline,
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )

    def test_01_valid_weight_distributions_pass_validation(self):
        """Valid weight distributions totaling exactly 100% pass clean and form validation."""
        valid_distributions = [
            (50, 25, 25),
            (60, 20, 20),
            (100, 0, 0),
            (0, 50, 50),
            (34, 33, 33),
        ]
        for w_gh, w_deliv, w_peer in valid_distributions:
            self.project.weight_github = w_gh
            self.project.weight_deliverables = w_deliv
            self.project.weight_peer = w_peer
            self.project.clean()

            form = ProjectForm(data={
                'title': 'Test Project',
                'description': 'Valid weights',
                'section': self.section.pk,
                'deadline': self.deadline.strftime('%Y-%m-%dT%H:%M'),
                'weight_github': w_gh,
                'weight_deliverables': w_deliv,
                'weight_peer': w_peer
            }, user=self.instructor)
            self.assertTrue(form.is_valid(), form.errors)

    def test_02_incorrect_total_weight_under_100_rejected(self):
        """Weights totaling less than 100% are rejected by model and form."""
        self.project.weight_github = 30
        self.project.weight_deliverables = 30
        self.project.weight_peer = 30  # total = 90%
        with self.assertRaises(ValidationError) as ctx:
            self.project.clean()
        self.assertIn("Your current total is 90%", str(ctx.exception))

        form = ProjectForm(data={
            'title': 'Under 100',
            'section': self.section.pk,
            'deadline': self.deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 30,
            'weight_deliverables': 30,
            'weight_peer': 30
        }, user=self.instructor)
        self.assertFalse(form.is_valid())
        self.assertTrue(any("90%" in err for err in form.non_field_errors()))

    def test_03_incorrect_total_weight_over_100_rejected(self):
        """Weights totaling greater than 100% are rejected by model and form."""
        self.project.weight_github = 50
        self.project.weight_deliverables = 40
        self.project.weight_peer = 30  # total = 120%
        with self.assertRaises(ValidationError) as ctx:
            self.project.clean()
        self.assertIn("Your current total is 120%", str(ctx.exception))

        form = ProjectForm(data={
            'title': 'Over 100',
            'section': self.section.pk,
            'deadline': self.deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': 50,
            'weight_deliverables': 40,
            'weight_peer': 30
        }, user=self.instructor)
        self.assertFalse(form.is_valid())
        self.assertTrue(any("120%" in err for err in form.non_field_errors()))

    def test_04_missing_or_none_weights_handling(self):
        """Missing weights in form fail validation; model clean handles None as 0."""
        # Form requires weight fields
        form = ProjectForm(data={
            'title': 'Missing Weights',
            'section': self.section.pk,
            'deadline': self.deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': '',
            'weight_deliverables': 50,
            'weight_peer': 50
        }, user=self.instructor)
        self.assertFalse(form.is_valid())
        self.assertIn('weight_github', form.errors)

        # Model treats None as 0
        self.project.weight_github = None
        self.project.weight_deliverables = 50
        self.project.weight_peer = 50
        self.project.clean()  # 0 + 50 + 50 = 100% passes

        self.project.weight_peer = 30
        with self.assertRaises(ValidationError):
            self.project.clean()  # 0 + 50 + 30 = 80% fails

    def test_05_invalid_negative_or_out_of_range_form_values(self):
        """Form rejects negative values and values exceeding 100."""
        form = ProjectForm(data={
            'title': 'Invalid Value',
            'section': self.section.pk,
            'deadline': self.deadline.strftime('%Y-%m-%dT%H:%M'),
            'weight_github': -10,
            'weight_deliverables': 60,
            'weight_peer': 50
        }, user=self.instructor)
        self.assertFalse(form.is_valid())
        self.assertIn('weight_github', form.errors)

    def test_06_course_policy_weights_validation(self):
        """CourseAssessmentPolicy enforces exact 100% total weight."""
        policy = CourseAssessmentPolicy(
            course=self.course,
            weight_github=50,
            weight_deliverables=30,
            weight_peer=10  # total = 90%
        )
        with self.assertRaises(ValidationError) as ctx:
            policy.clean()
        self.assertIn("Course policy weights must sum to exactly 100%", str(ctx.exception))
