
import csv
import io
import os
import sys
from datetime import timedelta
from unittest.mock import patch

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from academic.models import (
    Course, CourseSection, Project, Team, TeamMember,
    NonCodingDeliverable, DeliverableContribution,
    EvaluationCriterion, PeerEvaluation, PeerEvaluationScore,
    FinalAssessment
)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class FinalApprovalAndReportGenerationIntegrationTests(TestCase):
    """
    Integration tests for final approval and report generation.
    Acceptance criteria: Tests verify that approved scores and supporting evidence
    appear correctly in generated reports across 6 concise, effective test cases.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

        # 1. Users
        self.instructor = User.objects.create_user(
            email="inst_final_report@test.com",
            name="Dr. Leslie Lamport",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.coordinator = User.objects.create_user(
            email="coord_final_report@test.com",
            name="Coord Barbara Liskov",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.student_alice = User.objects.create_user(
            email="alice_final_rep@test.com",
            name="Alice Smith",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_alice.github_username = "alice_rep"
        self.student_alice.save()

        self.student_bob = User.objects.create_user(
            email="bob_final_rep@test.com",
            name="Bob Jones",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob.github_username = "bob_rep"
        self.student_bob.save()

        # 2. Academic Hierarchy
        self.course = Course.objects.create(
            course_code="CSE491",
            course_name="Distributed Consensus Capstone",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.student_alice, self.student_bob)

        # Configured weights: Deliverables 60%, Peer 40%, GitHub 0%
        self.project = Project.objects.create(
            section=self.section,
            title="Consensus Engine Capstone",
            deadline=timezone.now() + timedelta(days=14),
            weight_github=0,
            weight_deliverables=60,
            weight_peer=40
        )

        # Team 1: Alpha Team
        self.team_alpha = Team.objects.create(
            project=self.project,
            team_name="Alpha Team",
            github_repo_url="https://github.com/capstone/alpha"
        )
        TeamMember.objects.create(team=self.team_alpha, user=self.student_alice, role_in_team="Lead Architect")
        TeamMember.objects.create(team=self.team_alpha, user=self.student_bob, role_in_team="Core Developer")

        # Deliverables Evidence
        d1 = NonCodingDeliverable.objects.create(
            team=self.team_alpha,
            submitted_by=self.student_alice,
            title="Raft Algorithm Design Doc",
            link="https://docs.alpha.io/raft"
        )
        DeliverableContribution.objects.create(
            deliverable=d1,
            student=self.student_alice,
            contribution_area="Leader Election",
            status='VERIFIED'
        )

        d2 = NonCodingDeliverable.objects.create(
            team=self.team_alpha,
            submitted_by=self.student_bob,
            title="Log Replication State Machine",
            link="https://docs.alpha.io/sm"
        )
        DeliverableContribution.objects.create(
            deliverable=d2,
            student=self.student_bob,
            contribution_area="Log Consistency",
            status='VERIFIED'
        )

        # Peer Evaluation Evidence
        crit = EvaluationCriterion.objects.create(
            project=self.project,
            name="Technical Rigor",
            max_score=5
        )
        pe_bob_to_alice = PeerEvaluation.objects.create(
            team=self.team_alpha,
            evaluator=self.student_bob,
            evaluatee=self.student_alice,
            general_feedback="Outstanding consensus protocol implementation."
        )
        PeerEvaluationScore.objects.create(evaluation=pe_bob_to_alice, criterion=crit, score=5)

        pe_alice_to_bob = PeerEvaluation.objects.create(
            team=self.team_alpha,
            evaluator=self.student_alice,
            evaluatee=self.student_bob,
            general_feedback="Reliable state machine execution."
        )
        PeerEvaluationScore.objects.create(evaluation=pe_alice_to_bob, criterion=crit, score=4)

        # URLs
        self.team_scores_url = reverse('team_contribution_scores', kwargs={'team_id': self.team_alpha.pk})
        self.alice_detail_url = reverse('student_evidence_detail', kwargs={
            'team_id': self.team_alpha.pk,
            'student_id': self.student_alice.user_id
        })
        self.team_report_url = reverse('team_assessment_report', kwargs={'team_id': self.team_alpha.pk})
        self.project_report_url = reverse('project_assessment_report', kwargs={'project_id': self.project.pk})
        self.reports_hub_url = reverse('reports_hub')

        self.client.force_login(self.instructor)

    # -------------------------------------------------------------------------
    # TEST 1: Single Student Approval Integration with Team Report
    # -------------------------------------------------------------------------
    def test_01_single_approval_and_team_report_integration(self):
        """Verifies individual approval with viva notes renders accurately in generated team report."""
        # Instructor approves Alice with adjusted score and viva observations
        post_resp = self.client.post(self.alice_detail_url, {
            'action': 'save_and_approve',
            'viva_observations': 'Demonstrated deep understanding of Raft term split vote handling.',
            'adjusted_score': '95.0',
            'adjustment_reason': 'Flawless viva explanation of split-brain prevention.'
        })
        self.assertEqual(post_resp.status_code, 302)

        # Fetch Team Assessment Report (HTML)
        report_resp = self.client.get(self.team_report_url)
        self.assertEqual(report_resp.status_code, 200)

        # Verify summary stats
        self.assertEqual(report_resp.context['approved_count'], 1)
        self.assertEqual(report_resp.context['total_members'], 2)

        content = report_resp.content.decode('utf-8')
        # Alice is Approved with adjusted score & approver name
        self.assertIn("Alice Smith", content)
        self.assertIn("95.0%", content)
        self.assertIn("Approved", content)
        self.assertIn("Dr. Leslie Lamport", content)
        self.assertIn("Demonstrated deep understanding of Raft term split vote handling.", content)
        self.assertIn("Flawless viva explanation of split-brain prevention.", content)

        # Bob remains Pending approval
        self.assertIn("Bob Jones", content)
        self.assertIn("Pending", content)

    # -------------------------------------------------------------------------
    # TEST 2: Bulk Team Approval Integration with CSV Export
    # -------------------------------------------------------------------------
    def test_02_bulk_approval_and_team_csv_export_integration(self):
        """Verifies bulk team approval propagates to official CSV report with all supporting metadata."""
        # Perform bulk approval across the team
        bulk_resp = self.client.post(self.team_scores_url, {'action': 'approve_all_team'})
        self.assertEqual(bulk_resp.status_code, 302)

        # Request CSV Export
        csv_resp = self.client.get(f"{self.team_report_url}?export=csv")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertEqual(csv_resp['Content-Type'], 'text/csv')
        self.assertIn('Assessment_Report_Alpha_Team.csv', csv_resp['Content-Disposition'])

        reader = list(csv.reader(io.StringIO(csv_resp.content.decode('utf-8'))))
        header = reader[0]
        self.assertIn('Student Name', header)
        self.assertIn('Approval Status', header)
        self.assertIn('Approved By', header)
        self.assertIn('Final Official Score (%)', header)

        # Verify all members are marked Approved by the instructor
        rows = {r[0]: r for r in reader[1:]}
        self.assertIn('Alice Smith', rows)
        self.assertIn('Bob Jones', rows)

        for name, row in rows.items():
            self.assertEqual(row[9], 'Approved')
            self.assertEqual(row[10], 'Dr. Leslie Lamport')
            self.assertTrue(float(row[8]) > 0.0)  # Final Official Score

    # -------------------------------------------------------------------------
    # TEST 3: Supporting Evidence Alignment Across Multi-Pillars
    # -------------------------------------------------------------------------
    @patch('academic.utils.fetch_team_commits')
    def test_03_supporting_evidence_alignment_across_pillars(self, mock_fetch):
        """Verifies supporting GitHub, deliverable, and peer review evidence align with scores in reports."""
        self.project.weight_github = 30
        self.project.weight_deliverables = 40
        self.project.weight_peer = 30
        self.project.save()

        mock_fetch.return_value = {
            'status': 'success',
            'commits': [
                {
                    'sha': 'c123',
                    'author_username': 'alice_rep',
                    'date': '2026-10-20T10:00:00Z',
                    'additions': 250,
                    'deletions': 10,
                    'message': 'Raft election heartbeat',
                    'is_merge': False
                }
            ]
        }

        # Approve Alice's score
        self.client.post(self.alice_detail_url, {
            'action': 'save_and_approve',
            'viva_observations': 'Verified commit authenticity.',
            'adjusted_score': '92.0',
            'adjustment_reason': 'Excellent code walkthrough.'
        })

        # Fetch CSV report to inspect evidence alignment
        csv_resp = self.client.get(f"{self.team_report_url}?export=csv")
        reader = list(csv.reader(io.StringIO(csv_resp.content.decode('utf-8'))))
        alice_row = next(r for r in reader[1:] if r[0] == 'Alice Smith')

        # Supporting evidence columns
        self.assertEqual(alice_row[1], 'Lead Architect')  # Role
        self.assertEqual(alice_row[2], 'alice_rep')       # GitHub username
        self.assertNotEqual(alice_row[3], 'N/A')          # GitHub score
        self.assertNotEqual(alice_row[4], 'N/A')          # Deliverables score
        self.assertNotEqual(alice_row[5], 'N/A')          # Peer score
        self.assertEqual(alice_row[8], '92.0')            # Final Official Score
        self.assertEqual(alice_row[9], 'Approved')

    # -------------------------------------------------------------------------
    # TEST 4: Approval Locking and Unlocking Flow in Reports
    # -------------------------------------------------------------------------
    def test_04_approval_locking_and_unlocking_report_flow(self):
        """Verifies unlocking an approved score updates the report status dynamically."""
        # 1. Initially approve Alice
        FinalAssessment.objects.create(
            project=self.project,
            team=self.team_alpha,
            student=self.student_alice,
            recommended_score=88.0,
            adjusted_score=94.0,
            is_approved=True,
            approved_by=self.instructor,
            approved_at=timezone.now()
        )

        resp1 = self.client.get(self.team_report_url)
        self.assertEqual(resp1.context['approved_count'], 1)

        # 2. Unlock approval via student evidence detail
        unlock_resp = self.client.post(self.alice_detail_url, {
            'action': 'unapprove_score',
            'viva_observations': 'Reopened for additional viva questioning.',
            'adjusted_score': '94.0'
        })
        self.assertEqual(unlock_resp.status_code, 302)

        # 3. Verify report immediately reflects Pending status and decremented count
        resp2 = self.client.get(self.team_report_url)
        self.assertEqual(resp2.context['approved_count'], 0)
        content = resp2.content.decode('utf-8')
        self.assertIn("0 / 2 Approved", content)
        self.assertIn("Pending", content)

    # -------------------------------------------------------------------------
    # TEST 5: Multi-Team Class Assessment Report Integration (HTML & CSV)
    # -------------------------------------------------------------------------
    def test_05_multi_team_class_report_aggregation(self):
        """Verifies project-wide class report consolidates scores, teams, and approvals accurately."""
        # Setup Team 2 (Beta Team) with student Charlie
        student_charlie = User.objects.create_user(
            email="charlie_final_rep@test.com",
            name="Charlie Brown",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.section.students.add(student_charlie)
        team_beta = Team.objects.create(project=self.project, team_name="Beta Team")
        TeamMember.objects.create(team=team_beta, user=student_charlie, role_in_team="Security Analyst")

        d_charlie = NonCodingDeliverable.objects.create(
            team=team_beta,
            submitted_by=student_charlie,
            title="TLS Security Audit",
            link="https://docs.beta.io/sec"
        )
        DeliverableContribution.objects.create(
            deliverable=d_charlie,
            student=student_charlie,
            contribution_area="Cipher Suites",
            status='VERIFIED'
        )

        # Approve Alice (Team Alpha) and Charlie (Team Beta)
        FinalAssessment.objects.create(
            project=self.project,
            team=self.team_alpha,
            student=self.student_alice,
            recommended_score=88.0,
            adjusted_score=94.0,
            viva_observations="Alpha lead defense passed.",
            is_approved=True,
            approved_by=self.instructor,
            approved_at=timezone.now()
        )
        FinalAssessment.objects.create(
            project=self.project,
            team=team_beta,
            student=student_charlie,
            recommended_score=80.0,
            adjusted_score=85.0,
            viva_observations="Beta security defense passed.",
            is_approved=True,
            approved_by=self.instructor,
            approved_at=timezone.now()
        )

        # Part A: Class HTML Report
        resp_html = self.client.get(self.project_report_url)
        self.assertEqual(resp_html.status_code, 200)
        self.assertEqual(resp_html.context['total_members'], 3)
        self.assertEqual(resp_html.context['approved_count'], 2)

        content = resp_html.content.decode('utf-8')
        self.assertIn("Alpha Team", content)
        self.assertIn("Beta Team", content)
        self.assertIn("Charlie Brown", content)
        self.assertIn("Beta security defense passed.", content)

        # Part B: Class CSV Report
        resp_csv = self.client.get(f"{self.project_report_url}?export=csv")
        self.assertEqual(resp_csv.status_code, 200)
        self.assertIn('Project_Assessment_Report_Consensus_Engine_Capstone.csv', resp_csv['Content-Disposition'])

        reader = list(csv.reader(io.StringIO(resp_csv.content.decode('utf-8'))))
        header = reader[0]
        self.assertEqual(header[0], 'Team')
        self.assertEqual(header[1], 'Student Name')

        csv_rows = {r[1]: r for r in reader[1:]}
        self.assertEqual(csv_rows['Alice Smith'][0], 'Alpha Team')
        self.assertEqual(csv_rows['Alice Smith'][9], '94.0')
        self.assertEqual(csv_rows['Alice Smith'][10], 'Approved')

        self.assertEqual(csv_rows['Charlie Brown'][0], 'Beta Team')
        self.assertEqual(csv_rows['Charlie Brown'][9], '85.0')
        self.assertEqual(csv_rows['Charlie Brown'][10], 'Approved')

    # -------------------------------------------------------------------------
    # TEST 6: Role Authorization and Access Control for Report Hub & Generation
    # -------------------------------------------------------------------------
    def test_06_role_authorization_and_access_control(self):
        """Verifies authorized faculty can access report hubs while students are strictly restricted."""
        # 1. Instructor access to reports hub -> 200
        self.assertEqual(self.client.get(self.reports_hub_url).status_code, 200)

        # 2. Coordinator access to reports hub and project report -> 200
        self.client.force_login(self.coordinator)
        self.assertEqual(self.client.get(self.reports_hub_url).status_code, 200)
        self.assertEqual(self.client.get(self.project_report_url).status_code, 200)

        # 3. Student access is blocked and redirected to student_dashboard
        self.client.force_login(self.student_alice)
        hub_resp = self.client.get(self.reports_hub_url)
        self.assertEqual(hub_resp.status_code, 302)
        self.assertRedirects(hub_resp, reverse('student_dashboard'))

        team_rep_resp = self.client.get(self.team_report_url)
        self.assertEqual(team_rep_resp.status_code, 302)
        self.assertRedirects(team_rep_resp, reverse('student_dashboard'))

        proj_rep_resp = self.client.get(self.project_report_url)
        self.assertEqual(proj_rep_resp.status_code, 302)
        self.assertRedirects(proj_rep_resp, reverse('student_dashboard'))

        # 4. Anonymous access redirects to login
        self.client.logout()
        anon_resp = self.client.get(self.team_report_url)
        self.assertEqual(anon_resp.status_code, 302)
        self.assertIn('/accounts/login/', anon_resp.url)

