import os
import sys
from datetime import timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from academic.models import Course, CourseSection, Project, CourseAssessmentPolicy, PolicyChangeRequest


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PolicyApplicationToProjectsIntegrationTests(TestCase):
    """
    Integration tests for policy application to projects.
    Acceptance criteria: Standard policy is correctly applied to a project
    and project-specific settings are preserved.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        self.coordinator = User.objects.create_user(
            email="coord_app@example.com",
            name="Coordinator App",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_app@example.com",
            name="Instructor App",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE303",
            course_name="Operating Systems",
            coordinator=self.coordinator
        )
        self.standard_policy = CourseAssessmentPolicy.objects.create(
            course=self.course,
            weight_github=50,
            weight_deliverables=25,
            weight_peer=25
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 01",
            instructor=self.instructor
        )
        self.project_deadline = timezone.now() + timedelta(days=20)
        self.project = Project.objects.create(
            section=self.section,
            title="OS Kernel Project",
            deadline=self.project_deadline,
            weight_github=50,
            weight_deliverables=25,
            weight_peer=25
        )

    def test_01_standard_policy_applied_on_project_creation(self):
        """New project created by instructor automatically inherits standard course policy weights."""
        self.client.force_login(self.instructor)
        deadline_str = (timezone.now() + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M')
        resp = self.client.post(reverse('dashboard_redirect'), {
            'title': 'New Inherited Project',
            'description': 'Should inherit standard policy',
            'section': self.section.pk,
            'deadline': deadline_str
        })
        self.assertEqual(resp.status_code, 302)

        created_project = Project.objects.get(title='New Inherited Project')
        self.assertEqual(created_project.weight_github, self.standard_policy.weight_github)
        self.assertEqual(created_project.weight_deliverables, self.standard_policy.weight_deliverables)
        self.assertEqual(created_project.weight_peer, self.standard_policy.weight_peer)

    def test_02_coordinator_policy_update_syncs_to_course_projects(self):
        """Coordinator updates course policy and changes cascade to all course projects."""
        self.client.force_login(self.coordinator)
        url = reverse('update_course_policy', kwargs={'course_id': self.course.pk})
        resp = self.client.post(url, {
            'weight_github': '45',
            'weight_deliverables': '35',
            'weight_peer': '20'
        })
        self.assertEqual(resp.status_code, 302)

        self.standard_policy.refresh_from_db()
        self.assertEqual(self.standard_policy.weight_github, 45)

        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 45)
        self.assertEqual(self.project.weight_deliverables, 35)
        self.assertEqual(self.project.weight_peer, 20)

    def test_03_project_specific_policy_request_and_approval(self):
        """Instructor requests project-specific weights and coordinator approval applies them."""
        self.client.force_login(self.instructor)
        req_url = reverse('submit_policy_request', kwargs={'project_id': self.project.pk})
        self.client.post(req_url, {
            'proposed_github': '60',
            'proposed_deliverables': '20',
            'proposed_peer': '20',
            'justification': 'More emphasis on kernel code'
        })

        policy_req = PolicyChangeRequest.objects.get(project=self.project, status='PENDING')
        self.client.force_login(self.coordinator)
        rev_url = reverse('review_policy_request', kwargs={'request_id': policy_req.pk})
        resp = self.client.post(rev_url, {'action': 'APPROVE'})
        self.assertEqual(resp.status_code, 302)

        policy_req.refresh_from_db()
        self.assertEqual(policy_req.status, 'APPROVED')
        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 60)
        self.assertEqual(self.project.weight_deliverables, 20)
        self.assertEqual(self.project.weight_peer, 20)

    def test_04_rejected_policy_request_preserves_existing_settings(self):
        """Rejecting a custom policy request preserves the project's existing weight settings."""
        policy_req = PolicyChangeRequest.objects.create(
            project=self.project,
            instructor=self.instructor,
            proposed_github=70,
            proposed_deliverables=15,
            proposed_peer=15,
            justification="Experimental weights"
        )
        self.client.force_login(self.coordinator)
        rev_url = reverse('review_policy_request', kwargs={'request_id': policy_req.pk})
        resp = self.client.post(rev_url, {'action': 'REJECT'})
        self.assertEqual(resp.status_code, 302)

        policy_req.refresh_from_db()
        self.assertEqual(policy_req.status, 'REJECTED')
        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 50)
        self.assertEqual(self.project.weight_deliverables, 25)
        self.assertEqual(self.project.weight_peer, 25)

    def test_05_course_policy_isolation_preserves_other_course_projects(self):
        """Updating Course A policy does not affect projects in Course B."""
        coord_b = User.objects.create_user(
            email="coord_b@example.com",
            name="Coordinator B",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        course_b = Course.objects.create(
            course_code="CSE304",
            course_name="Computer Networks",
            coordinator=coord_b
        )
        section_b = CourseSection.objects.create(
            course=course_b,
            section_name="Section 01",
            instructor=self.instructor
        )
        project_b = Project.objects.create(
            section=section_b,
            title="Networks Socket Project",
            deadline=self.project_deadline,
            weight_github=30,
            weight_deliverables=40,
            weight_peer=30
        )

        self.client.force_login(self.coordinator)
        url = reverse('update_course_policy', kwargs={'course_id': self.course.pk})
        self.client.post(url, {
            'weight_github': '70',
            'weight_deliverables': '20',
            'weight_peer': '10'
        })

        # Course A project updated
        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 70)

        # Course B project preserved
        project_b.refresh_from_db()
        self.assertEqual(project_b.weight_github, 30)
        self.assertEqual(project_b.weight_deliverables, 40)
        self.assertEqual(project_b.weight_peer, 30)

    def test_06_unauthorized_user_cannot_update_course_policy(self):
        """Instructor cannot modify course policy; weights remain unchanged."""
        self.client.force_login(self.instructor)
        url = reverse('update_course_policy', kwargs={'course_id': self.course.pk})
        resp = self.client.post(url, {
            'weight_github': '80',
            'weight_deliverables': '10',
            'weight_peer': '10'
        })
        self.assertEqual(resp.status_code, 302)

        self.standard_policy.refresh_from_db()
        self.assertEqual(self.standard_policy.weight_github, 50)
