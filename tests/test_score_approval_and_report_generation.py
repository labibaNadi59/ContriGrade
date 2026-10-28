import csv
import io
import os
import sys
from datetime import timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from academic.models import (
    Course, CourseSection, Project, Team, TeamMember,
    NonCodingDeliverable, DeliverableContribution, FinalAssessment
)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ScoreApprovalAndReportGenerationUnitTests(TestCase):
    """
    Unit tests for score approval rules, report content, and report generation (HTML & CSV).
    Acceptance criteria: Tests verify approval rules, report content,
    and report generation for valid assessment data.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        # Users
        self.instructor = User.objects.create_user(
            email="inst_report@test.com",
            name="Dr. Leslie Lamport",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.coordinator = User.objects.create_user(
            email="coord_report@test.com",
            name="Coord Barbara Liskov",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.student_alice = User.objects.create_user(
            email="alice_report@test.com",
            name="Alice Smith",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob = User.objects.create_user(
            email="bob_report@test.com",
            name="Bob Jones",
            role=User.Role.STUDENT,
            password="password123"
        )

        # Academic hierarchy
        self.course = Course.objects.create(
            course_code="CSE490",
            course_name="Distributed Systems Capstone",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student_alice, self.student_bob)

        self.project = Project.objects.create(
            section=self.section,
            title="Consensus Engine Project",
            deadline=timezone.now() + timedelta(days=14),
            weight_github=0,
            weight_deliverables=100,
            weight_peer=0
        )

        # Team 1: Alpha Team (Alice & Bob)
        self.team_1 = Team.objects.create(
            project=self.project,
            team_name="Alpha Team"
        )
        TeamMember.objects.create(team=self.team_1, user=self.student_alice, role_in_team="Lead Architect")
        TeamMember.objects.create(team=self.team_1, user=self.student_bob, role_in_team="Core Developer")

        # Verified deliverables for team 1
        d1 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_alice, title="Raft Architecture Spec", link="https://docs.alpha.io/raft")
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_alice, contribution_area="Consensus Protocol", status='VERIFIED')
        d2 = NonCodingDeliverable.objects.create(team=self.team_1, submitted_by=self.student_bob, title="State Machine Implementation", link="https://docs.alpha.io/sm")
        DeliverableContribution.objects.create(deliverable=d2, student=self.student_bob, contribution_area="Log Replication", status='VERIFIED')

        # URLs
        self.team_scores_url = reverse('team_contribution_scores', kwargs={'team_id': self.team_1.pk})
        self.team_report_url = reverse('team_assessment_report', kwargs={'team_id': self.team_1.pk})
        self.project_report_url = reverse('project_assessment_report', kwargs={'project_id': self.project.pk})

        self.client.force_login(self.instructor)

    # -------------------------------------------------------------------------
    # TEST 1: Single Student Score Approval and Toggle Rule
    # -------------------------------------------------------------------------
    def test_01_single_student_approval_and_toggle_rule(self):
        """Verifies instructor can approve an individual student's score and toggle it to unlock."""
        # 1. Approve Alice single
        response = self.client.post(self.team_scores_url, {
            'action': 'approve_single',
            'student_id': self.student_alice.user_id,
        })
        self.assertEqual(response.status_code, 302)

        fa = FinalAssessment.objects.get(project=self.project, student=self.student_alice)
        self.assertTrue(fa.is_approved)
        self.assertEqual(fa.approved_by, self.instructor)
        self.assertIsNotNone(fa.approved_at)

        # 2. Toggle approval off (unlock for editing)
        response_toggle = self.client.post(self.team_scores_url, {
            'action': 'approve_single',
            'student_id': self.student_alice.user_id,
        })
        self.assertEqual(response_toggle.status_code, 302)

        fa.refresh_from_db()
        self.assertFalse(fa.is_approved)
        self.assertIsNone(fa.approved_by)
        self.assertIsNone(fa.approved_at)

    # -------------------------------------------------------------------------
    # TEST 2: Bulk Team Score Approval Rule
    # -------------------------------------------------------------------------
    def test_02_bulk_team_score_approval_rule(self):
        """Verifies 'approve_all_team' marks all team members approved with audit metadata."""
        response = self.client.post(self.team_scores_url, {
            'action': 'approve_all_team',
        })
        self.assertEqual(response.status_code, 302)

        assessments = FinalAssessment.objects.filter(project=self.project, team=self.team_1)
        self.assertEqual(assessments.count(), 2)
        for fa in assessments:
            self.assertTrue(fa.is_approved)
            self.assertEqual(fa.approved_by, self.instructor)
            self.assertIsNotNone(fa.approved_at)

        # Confirm team scores view renders full approval metrics
        resp_view = self.client.get(self.team_scores_url)
        self.assertEqual(resp_view.context['approved_count'], 2)
        self.assertTrue(resp_view.context['all_approved'])

    # -------------------------------------------------------------------------
    # TEST 3: Access Control and Role Authorization Rules
    # -------------------------------------------------------------------------
    def test_03_access_control_and_role_authorization_rules(self):
        """Verifies unauthorized students cannot perform score approvals or access assessment reports."""
        self.client.force_login(self.student_alice)

        # Attempt score approval POST as student -> redirected to student dashboard
        post_resp = self.client.post(self.team_scores_url, {'action': 'approve_all_team'})
        self.assertEqual(post_resp.status_code, 302)
        self.assertRedirects(post_resp, reverse('student_dashboard'))
        self.assertFalse(FinalAssessment.objects.filter(project=self.project, is_approved=True).exists())

        # Attempt team assessment report GET as student -> redirected to student dashboard
        team_rep_resp = self.client.get(self.team_report_url)
        self.assertEqual(team_rep_resp.status_code, 302)
        self.assertRedirects(team_rep_resp, reverse('student_dashboard'))

        # Attempt project assessment report GET as student -> redirected to student dashboard
        proj_rep_resp = self.client.get(self.project_report_url)
        self.assertEqual(proj_rep_resp.status_code, 302)
        self.assertRedirects(proj_rep_resp, reverse('student_dashboard'))

        # Attempt unauthenticated (anonymous) access -> redirected to login
        self.client.logout()
        anon_resp = self.client.get(self.team_report_url)
        self.assertEqual(anon_resp.status_code, 302)
        self.assertIn('/accounts/login/', anon_resp.url)

    # -------------------------------------------------------------------------
    # TEST 4: Team Assessment Report HTML Content
    # -------------------------------------------------------------------------
    def test_04_team_assessment_report_html_content(self):
        """Verifies team assessment report renders valid assessment data, scores, viva notes, and approval status."""
        # Setup assessment with adjustment and viva notes for Alice
        FinalAssessment.objects.create(
            project=self.project,
            team=self.team_1,
            student=self.student_alice,
            recommended_score=80.0,
            adjusted_score=92.0,
            adjustment_reason="Superb technical viva defense",
            viva_observations="Explained Paxos vs Raft trade-offs flawlessly.",
            is_approved=True,
            approved_by=self.instructor,
            approved_at=timezone.now()
        )

        response = self.client.get(self.team_report_url)
        self.assertEqual(response.status_code, 200)

        # Context assertions
        self.assertEqual(response.context['team'], self.team_1)
        self.assertEqual(response.context['project'], self.project)
        self.assertEqual(response.context['approved_count'], 1)
        self.assertEqual(response.context['total_members'], 2)

        # HTML content assertions
        content = response.content.decode('utf-8')
        self.assertIn("Alpha Team", content)
        self.assertIn("Alice Smith", content)
        self.assertIn("92.0%", content)  # Adjusted / Effective score
        self.assertIn("Explained Paxos vs Raft trade-offs flawlessly.", content)
        self.assertIn("Superb technical viva defense", content)
        self.assertIn("Approved", content)
        self.assertIn("Dr. Leslie Lamport", content)

    # -------------------------------------------------------------------------
    # TEST 5: Team Assessment Report CSV Generation
    # -------------------------------------------------------------------------
    def test_05_team_assessment_report_csv_generation(self):
        """Verifies team CSV export generates valid columns, attachment header, and student assessment data."""
        FinalAssessment.objects.create(
            project=self.project,
            team=self.team_1,
            student=self.student_alice,
            recommended_score=80.0,
            adjusted_score=88.0,
            adjustment_reason="Excellent live demo",
            viva_observations="Demonstrated consensus failover live.",
            is_approved=True,
            approved_by=self.instructor,
            approved_at=timezone.now()
        )

        response = self.client.get(f"{self.team_report_url}?export=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment; filename="Assessment_Report_Alpha_Team.csv"', response['Content-Disposition'])

        csv_content = response.content.decode('utf-8')
        reader = list(csv.reader(io.StringIO(csv_content)))

        # Verify header structure
        header = reader[0]
        self.assertIn('Student Name', header)
        self.assertIn('Final Official Score (%)', header)
        self.assertIn('Approval Status', header)
        self.assertIn('Approved By', header)
        self.assertIn('Viva Observations', header)
        self.assertIn('Adjustment Reason', header)

        # Verify Alice's row data
        alice_row = next(r for r in reader[1:] if r[0] == 'Alice Smith')
        self.assertEqual(alice_row[1], 'Lead Architect')
        self.assertEqual(alice_row[8], '88.0')  # Final Official Score
        self.assertEqual(alice_row[9], 'Approved')  # Approval Status
        self.assertEqual(alice_row[10], 'Dr. Leslie Lamport')  # Approved By
        self.assertEqual(alice_row[12], 'Demonstrated consensus failover live.')  # Viva Observations
        self.assertEqual(alice_row[13], 'Excellent live demo')  # Adjustment Reason

    # -------------------------------------------------------------------------
    # TEST 6: Project-Wide Assessment Report Generation (HTML & CSV)
    # -------------------------------------------------------------------------
    def test_06_project_assessment_report_generation(self):
        """Verifies class-wide project assessment report correctly consolidates multiple teams in HTML & CSV."""
        # Create Team 2: Beta Team with Charlie
        student_charlie = User.objects.create_user(
            email="charlie_report@test.com",
            name="Charlie Brown",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.section.students.add(student_charlie)
        team_2 = Team.objects.create(project=self.project, team_name="Beta Team")
        TeamMember.objects.create(team=team_2, user=student_charlie, role_in_team="Security Lead")

        # Deliverable for Team 2
        d_charlie = NonCodingDeliverable.objects.create(team=team_2, submitted_by=student_charlie, title="TLS Encryption Audit", link="https://docs.beta.io/sec")
        DeliverableContribution.objects.create(deliverable=d_charlie, student=student_charlie, contribution_area="Crypto", status='VERIFIED')

        # Part A: HTML Report
        resp_html = self.client.get(self.project_report_url)
        self.assertEqual(resp_html.status_code, 200)
        self.assertTrue(resp_html.context['is_project_wide'])
        self.assertEqual(resp_html.context['total_members'], 3)
        html_content = resp_html.content.decode('utf-8')
        self.assertIn("Consensus Engine Project", html_content)
        self.assertIn("Alpha Team", html_content)
        self.assertIn("Beta Team", html_content)
        self.assertIn("Charlie Brown", html_content)

        # Part B: CSV Export
        resp_csv = self.client.get(f"{self.project_report_url}?export=csv")
        self.assertEqual(resp_csv.status_code, 200)
        self.assertEqual(resp_csv['Content-Type'], 'text/csv')
        self.assertIn('Project_Assessment_Report_Consensus_Engine_Project.csv', resp_csv['Content-Disposition'])

        csv_content = resp_csv.content.decode('utf-8')
        reader = list(csv.reader(io.StringIO(csv_content)))
        header = reader[0]
        self.assertEqual(header[0], 'Team')
        self.assertEqual(header[1], 'Student Name')

        # Ensure both teams and all students are present in CSV
        team_names_in_csv = {r[0] for r in reader[1:]}
        student_names_in_csv = {r[1] for r in reader[1:]}
        self.assertIn('Alpha Team', team_names_in_csv)
        self.assertIn('Beta Team', team_names_in_csv)
        self.assertIn('Alice Smith', student_names_in_csv)
        self.assertIn('Charlie Brown', student_names_in_csv)
