

import os
import sys
from datetime import timedelta

from django.test import TestCase
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from django.contrib.messages import get_messages

from accounts.models import User
from academic.models import (
    Course, CourseSection, Project, Team, TeamMember,
    NonCodingDeliverable, DeliverableContribution
)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# =====================================================================
# SHARED BASE FIXTURE
# =====================================================================
class ClaimWorkflowBaseTestCase(TestCase):
    """Common setup for claim verification workflow tests."""

    def setUp(self):
        super().setUp()
        self.coordinator = User.objects.create_user(
            email="coord_cv@test.com",
            name="Coordinator Admin",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_cv@test.com",
            name="Instructor Davis",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.alice = User.objects.create_user(
            email="alice_cv@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.bob = User.objects.create_user(
            email="bob_cv@test.com",
            name="Bob Verifier",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.charlie = User.objects.create_user(
            email="charlie_cv@test.com",
            name="Charlie Rejector",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.outsider = User.objects.create_user(
            email="outsider_cv@test.com",
            name="David Outsider",
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
        self.section.students.add(self.alice, self.bob, self.charlie)

        self.project = Project.objects.create(
            section=self.section,
            title="E-Commerce Architecture",
            description="System design and implementation project",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Core Architects"
        )
        TeamMember.objects.create(team=self.team, user=self.alice)
        TeamMember.objects.create(team=self.team, user=self.bob)
        TeamMember.objects.create(team=self.team, user=self.charlie)

        self.deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.alice,
            title="Database ERD and Architecture",
            link="https://dbdocs.io/ecommerce-erd",
            description="Complete schema specification and diagrams."
        )

        self.claim_bob = DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.bob,
            contribution_area="Designed PostgreSQL normalization and schemas",
            status='PENDING'
        )
        self.claim_charlie = DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.charlie,
            contribution_area="Created indexing and partitioning plan",
            status='PENDING'
        )

        self.verify_url_bob = f"/academic/student/claim/{self.claim_bob.pk}/verify/"
        self.reject_url_bob = f"/academic/student/claim/{self.claim_bob.pk}/reject/"
        self.verify_url_charlie = f"/academic/student/claim/{self.claim_charlie.pk}/verify/"
        self.reject_url_charlie = f"/academic/student/claim/{self.claim_charlie.pk}/reject/"
        self.dashboard_url = "/academic/student/"
        self.progress_url = f"/academic/student/team/{self.team.team_id}/progress/"
        self.review_url = f"/academic/instructor/team/{self.team.pk}/deliverables/"


# =====================================================================
# 1. CLAIM VERIFICATION ACTION RECORDING TESTS
# =====================================================================
class ClaimVerificationActionRecordingTests(ClaimWorkflowBaseTestCase):
    """Verifies that verification and rejection actions are correctly recorded in the DB."""

    def test_verify_action_records_verified_status_in_db(self):
        """POST to verify_claim changes status from PENDING to VERIFIED in the database."""
        self.assertEqual(self.claim_bob.status, 'PENDING')
        self.client.force_login(self.bob)
        resp = self.client.post(self.verify_url_bob)

        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, self.dashboard_url)

        self.claim_bob.refresh_from_db()
        self.assertEqual(self.claim_bob.status, 'VERIFIED')

    def test_verify_action_queues_success_flash_message(self):
        """Successful verification queues the correct success flash message."""
        self.client.force_login(self.bob)
        resp = self.client.post(self.verify_url_bob, follow=True)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        expected_msg = f"Verified contribution for '{self.deliverable.title}'."
        self.assertIn(expected_msg, messages)

    def test_reject_action_records_rejected_status_in_db(self):
        """POST to reject_claim changes status from PENDING to REJECTED in the database."""
        self.assertEqual(self.claim_charlie.status, 'PENDING')
        self.client.force_login(self.charlie)
        resp = self.client.post(self.reject_url_charlie)

        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, self.dashboard_url)

        self.claim_charlie.refresh_from_db()
        self.assertEqual(self.claim_charlie.status, 'REJECTED')

    def test_reject_action_queues_success_flash_message(self):
        """Successful rejection queues the correct success flash message."""
        self.client.force_login(self.charlie)
        resp = self.client.post(self.reject_url_charlie, follow=True)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        expected_msg = f"Rejected contribution for '{self.deliverable.title}'."
        self.assertIn(expected_msg, messages)

    def test_get_request_on_verify_does_not_modify_claim_status(self):
        """GET request on verify_claim view does NOT modify claim status (must be POST)."""
        self.client.force_login(self.bob)
        resp = self.client.get(self.verify_url_bob)

        self.assertEqual(resp.status_code, 302)
        self.claim_bob.refresh_from_db()
        self.assertEqual(self.claim_bob.status, 'PENDING')

    def test_get_request_on_reject_does_not_modify_claim_status(self):
        """GET request on reject_claim view does NOT modify claim status (must be POST)."""
        self.client.force_login(self.charlie)
        resp = self.client.get(self.reject_url_charlie)

        self.assertEqual(resp.status_code, 302)
        self.claim_charlie.refresh_from_db()
        self.assertEqual(self.claim_charlie.status, 'PENDING')

    def test_verify_action_is_idempotent(self):
        """Repeated POST to verify_claim keeps status VERIFIED and functions cleanly."""
        self.client.force_login(self.bob)
        self.client.post(self.verify_url_bob)
        self.client.post(self.verify_url_bob)

        self.claim_bob.refresh_from_db()
        self.assertEqual(self.claim_bob.status, 'VERIFIED')

    def test_reject_action_is_idempotent(self):
        """Repeated POST to reject_claim keeps status REJECTED and functions cleanly."""
        self.client.force_login(self.charlie)
        self.client.post(self.reject_url_charlie)
        self.client.post(self.reject_url_charlie)

        self.claim_charlie.refresh_from_db()
        self.assertEqual(self.claim_charlie.status, 'REJECTED')


# =====================================================================
# 2. SYSTEM-WIDE REFLECTION TESTS (DASHBOARD, PROGRESS, REVIEW)
# =====================================================================
class ClaimVerificationSystemReflectionTests(ClaimWorkflowBaseTestCase):
    """Verifies that verification and rejection actions are accurately reflected across the system."""

    def test_pending_claims_reflected_on_student_dashboard(self):
        """Pending claims appear in pending claims alert on the student dashboard."""
        self.client.force_login(self.bob)
        resp = self.client.get(self.dashboard_url)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.claim_bob, resp.context['pending_claims'])
        content = resp.content.decode('utf-8')
        self.assertIn("Action Required: Pending Verifications", content)
        self.assertIn(self.deliverable.title, content)
        self.assertIn("Alice Submitter", content)
        self.assertIn("Designed PostgreSQL normalization and schemas", content)
        self.assertIn("Verify", content)
        self.assertIn("Reject", content)

    def test_verified_claim_removed_from_student_dashboard(self):
        """After verification, the claim is removed from pending notifications on the dashboard."""
        self.client.force_login(self.bob)
        self.client.post(self.verify_url_bob)

        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.claim_bob, resp.context['pending_claims'])
        content = resp.content.decode('utf-8')
        self.assertNotIn("Action Required: Pending Verifications", content)

    def test_rejected_claim_removed_from_student_dashboard(self):
        """After rejection, the claim is removed from pending notifications on the dashboard."""
        self.client.force_login(self.charlie)
        self.client.post(self.reject_url_charlie)

        resp = self.client.get(self.dashboard_url)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(self.claim_charlie, resp.context['pending_claims'])
        content = resp.content.decode('utf-8')
        self.assertNotIn("Action Required: Pending Verifications", content)

    def test_students_only_see_their_own_pending_claims_on_dashboard(self):
        """Student dashboard isolates claims; students never see claims tagged for other teammates."""
        self.client.force_login(self.bob)
        resp_bob = self.client.get(self.dashboard_url)
        self.assertIn(self.claim_bob, resp_bob.context['pending_claims'])
        self.assertNotIn(self.claim_charlie, resp_bob.context['pending_claims'])

        self.client.force_login(self.charlie)
        resp_charlie = self.client.get(self.dashboard_url)
        self.assertIn(self.claim_charlie, resp_charlie.context['pending_claims'])
        self.assertNotIn(self.claim_bob, resp_charlie.context['pending_claims'])

    def test_pending_badge_reflected_on_student_team_progress(self):
        """Pending claim reflects a yellow 'Pending' badge on student_team_progress page."""
        self.client.force_login(self.alice)
        resp = self.client.get(self.progress_url)

        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Bob Verifier", content)
        self.assertIn("Designed PostgreSQL normalization and schemas", content)
        self.assertIn("Pending", content)

    def test_verified_badge_reflected_on_student_team_progress(self):
        """Verified claim reflects a green 'Verified' badge on student_team_progress page."""
        self.client.force_login(self.bob)
        self.client.post(self.verify_url_bob)

        self.client.force_login(self.alice)
        resp = self.client.get(self.progress_url)

        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Bob Verifier", content)
        self.assertIn("Verified", content)

    def test_rejected_badge_reflected_on_student_team_progress(self):
        """Rejected claim reflects a red 'Rejected' badge on student_team_progress page."""
        self.client.force_login(self.charlie)
        self.client.post(self.reject_url_charlie)

        self.client.force_login(self.alice)
        resp = self.client.get(self.progress_url)

        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Charlie Rejector", content)
        self.assertIn("Rejected", content)

    def test_mixed_badges_reflected_on_deliverable_with_multiple_claims(self):
        """Deliverable with Bob verified and Charlie rejected reflects both badges accurately."""
        self.client.force_login(self.bob)
        self.client.post(self.verify_url_bob)

        self.client.force_login(self.charlie)
        self.client.post(self.reject_url_charlie)

        self.client.force_login(self.alice)
        resp = self.client.get(self.progress_url)

        content = resp.content.decode('utf-8')
        self.assertIn("Bob Verifier", content)
        self.assertIn("Verified", content)
        self.assertIn("Charlie Rejector", content)
        self.assertIn("Rejected", content)

    def test_verification_and_rejection_reflected_on_instructor_review_hub(self):
        """Instructor peer review hub reflects both 'Verified by Peer' and 'Rejected by Peer'."""
        self.client.force_login(self.bob)
        self.client.post(self.verify_url_bob)

        self.client.force_login(self.charlie)
        self.client.post(self.reject_url_charlie)

        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)

        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Verified by Peer", content)
        self.assertIn("Rejected by Peer", content)

    def test_instructor_review_status_filter_reflects_verified_and_rejected(self):
        """Instructor filter '?status=VERIFIED' and '?status=REJECTED' isolate verified and rejected claims."""
        self.client.force_login(self.bob)
        self.client.post(self.verify_url_bob)

        self.client.force_login(self.charlie)
        self.client.post(self.reject_url_charlie)

        self.client.force_login(self.instructor)

        # Filter: VERIFIED
        resp_v = self.client.get(f"{self.review_url}?status=VERIFIED")
        delivs_v = resp_v.context['deliverables']
        self.assertEqual(len(delivs_v), 1)
        self.assertEqual(len(delivs_v[0].filtered_contributions), 1)
        self.assertEqual(delivs_v[0].filtered_contributions[0].status, 'VERIFIED')
        self.assertEqual(delivs_v[0].filtered_contributions[0].student, self.bob)

        # Filter: REJECTED
        resp_r = self.client.get(f"{self.review_url}?status=REJECTED")
        delivs_r = resp_r.context['deliverables']
        self.assertEqual(len(delivs_r), 1)
        self.assertEqual(len(delivs_r[0].filtered_contributions), 1)
        self.assertEqual(delivs_r[0].filtered_contributions[0].status, 'REJECTED')
        self.assertEqual(delivs_r[0].filtered_contributions[0].student, self.charlie)

        # Filter: PENDING (should have none left)
        resp_p = self.client.get(f"{self.review_url}?status=PENDING")
        self.assertEqual(len(resp_p.context['deliverables']), 0)


# =====================================================================
# 3. SECURITY, OWNERSHIP & DEADLINE ENFORCEMENT TESTS
# =====================================================================
class ClaimVerificationSecurityAndDeadlineTests(ClaimWorkflowBaseTestCase):
    """Verifies authorization checks, ownership security, and project deadline controls."""

    def test_student_cannot_verify_another_students_claim_returns_404(self):
        """Student Charlie cannot verify Bob's claim; request returns 404."""
        self.client.force_login(self.charlie)
        resp = self.client.post(self.verify_url_bob)

        self.assertEqual(resp.status_code, 404)
        self.claim_bob.refresh_from_db()
        self.assertEqual(self.claim_bob.status, 'PENDING')

    def test_student_cannot_reject_another_students_claim_returns_404(self):
        """Student Charlie cannot reject Bob's claim; request returns 404."""
        self.client.force_login(self.charlie)
        resp = self.client.post(self.reject_url_bob)

        self.assertEqual(resp.status_code, 404)
        self.claim_bob.refresh_from_db()
        self.assertEqual(self.claim_bob.status, 'PENDING')

    def test_submitter_cannot_verify_own_tagged_teammate_claim_returns_404(self):
        """Deliverable submitter Alice cannot verify Bob's claim; request returns 404."""
        self.client.force_login(self.alice)
        resp = self.client.post(self.verify_url_bob)

        self.assertEqual(resp.status_code, 404)
        self.claim_bob.refresh_from_db()
        self.assertEqual(self.claim_bob.status, 'PENDING')

    def test_outsider_student_cannot_verify_claim_returns_404(self):
        """Non-team member student David cannot verify Bob's claim; request returns 404."""
        self.client.force_login(self.outsider)
        resp = self.client.post(self.verify_url_bob)

        self.assertEqual(resp.status_code, 404)
        self.claim_bob.refresh_from_db()
        self.assertEqual(self.claim_bob.status, 'PENDING')

    def test_unauthenticated_user_redirected_to_login(self):
        """Unauthenticated user posting to verify or reject is redirected to login."""
        resp_v = self.client.post(self.verify_url_bob)
        self.assertEqual(resp_v.status_code, 302)
        self.assertIn("/accounts/login/", resp_v.url)

        resp_r = self.client.post(self.reject_url_bob)
        self.assertEqual(resp_r.status_code, 302)
        self.assertIn("/accounts/login/", resp_r.url)

    def test_non_student_roles_cannot_verify_or_reject_claims(self):
        """Instructor and coordinator accounts cannot access verify or reject views."""
        for user in [self.instructor, self.coordinator]:
            self.client.force_login(user)
            resp_v = self.client.post(self.verify_url_bob)
            self.assertEqual(resp_v.status_code, 403)

            resp_r = self.client.post(self.reject_url_bob)
            self.assertEqual(resp_r.status_code, 403)

    def test_verification_blocked_when_project_deadline_has_passed(self):
        """When project deadline has passed, verification is blocked and error message is set."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(minutes=10)
        )
        self.project.refresh_from_db()

        self.client.force_login(self.bob)
        resp = self.client.post(self.verify_url_bob, follow=True)

        self.claim_bob.refresh_from_db()
        self.assertEqual(self.claim_bob.status, 'PENDING')

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Cannot verify. The project deadline has passed.", messages)

    def test_rejection_blocked_when_project_deadline_has_passed(self):
        """When project deadline has passed, rejection is blocked and error message is set."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(minutes=10)
        )
        self.project.refresh_from_db()

        self.client.force_login(self.charlie)
        resp = self.client.post(self.reject_url_charlie, follow=True)

        self.claim_charlie.refresh_from_db()
        self.assertEqual(self.claim_charlie.status, 'PENDING')

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Cannot reject. The project deadline has passed.", messages)

    def test_passed_deadline_renders_locked_badge_on_student_dashboard(self):
        """When project deadline has passed, dashboard renders 'Project Locked' badge instead of buttons."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(minutes=10)
        )
        self.client.force_login(self.bob)
        resp = self.client.get(self.dashboard_url)

        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Project Locked", content)
        self.assertNotIn(f'action="{self.verify_url_bob}"', content)

    def test_verify_nonexistent_claim_id_returns_404(self):
        """POST to verify non-existent claim returns 404."""
        self.client.force_login(self.bob)
        resp = self.client.post("/academic/student/claim/999999/verify/")
        self.assertEqual(resp.status_code, 404)

    def test_reject_nonexistent_claim_id_returns_404(self):
        """POST to reject non-existent claim returns 404."""
        self.client.force_login(self.charlie)
        resp = self.client.post("/academic/student/claim/999999/reject/")
        self.assertEqual(resp.status_code, 404)


# =====================================================================
# 4. FULL INTEGRATION WORKFLOW TEST
# =====================================================================
class ClaimVerificationFullIntegrationTests(ClaimWorkflowBaseTestCase):
    """Tests the full multi-user collaboration workflow from submission to verification & rejection."""

    def test_complete_verification_and_rejection_workflow_lifecycle(self):
        """Full lifecycle:
        1. Initial state: Bob and Charlie have PENDING claims.
        2. Bob visits dashboard -> sees pending claim -> verifies it.
        3. Charlie visits dashboard -> sees pending claim -> rejects it.
        4. Both check team progress -> Bob is Verified, Charlie is Rejected.
        5. Instructor inspects review hub -> sees both claims with correct status.
        """
        # Step 1: Initial state
        self.assertEqual(self.claim_bob.status, 'PENDING')
        self.assertEqual(self.claim_charlie.status, 'PENDING')

        # Step 2: Bob verifies
        self.client.force_login(self.bob)
        r_dash = self.client.get(self.dashboard_url)
        self.assertIn("Action Required: Pending Verifications", r_dash.content.decode())
        r_ver = self.client.post(self.verify_url_bob, follow=True)
        self.assertEqual(r_ver.status_code, 200)
        self.claim_bob.refresh_from_db()
        self.assertEqual(self.claim_bob.status, 'VERIFIED')
        self.assertNotIn("Action Required: Pending Verifications", r_ver.content.decode())

        # Step 3: Charlie rejects
        self.client.force_login(self.charlie)
        r_dash_c = self.client.get(self.dashboard_url)
        self.assertIn("Action Required: Pending Verifications", r_dash_c.content.decode())
        r_rej = self.client.post(self.reject_url_charlie, follow=True)
        self.assertEqual(r_rej.status_code, 200)
        self.claim_charlie.refresh_from_db()
        self.assertEqual(self.claim_charlie.status, 'REJECTED')
        self.assertNotIn("Action Required: Pending Verifications", r_rej.content.decode())

        # Step 4: Check Team Progress page
        self.client.force_login(self.alice)
        r_prog = self.client.get(self.progress_url)
        content_prog = r_prog.content.decode('utf-8')
        self.assertIn("Bob Verifier", content_prog)
        self.assertIn("Verified", content_prog)
        self.assertIn("Charlie Rejector", content_prog)
        self.assertIn("Rejected", content_prog)

        # Step 5: Instructor inspects review hub
        self.client.force_login(self.instructor)
        r_rev = self.client.get(self.review_url)
        content_rev = r_rev.content.decode('utf-8')
        self.assertIn("Verified by Peer", content_rev)
        self.assertIn("Rejected by Peer", content_rev)


# =====================================================================
# 5. LIVE SELENIUM BROWSER E2E TESTS (HEADLESS CHROME)
# =====================================================================
class ClaimVerificationSeleniumE2ETests(StaticLiveServerTestCase):
    """Browser-level E2E tests verifying verification and rejection in a live browser."""

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
            email="coord_cv_e2e@test.com",
            name="Coord E2E",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_cv_e2e@test.com",
            name="Inst E2E",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.alice = User.objects.create_user(
            email="alice_cv_e2e@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.bob = User.objects.create_user(
            email="bob_cv_e2e@test.com",
            name="Bob Verifier",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.charlie = User.objects.create_user(
            email="charlie_cv_e2e@test.com",
            name="Charlie Rejector",
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
        self.section.students.add(self.alice, self.bob, self.charlie)

        self.project = Project.objects.create(
            section=self.section,
            title="Cloud Architecture",
            description="Microservices and cloud migration",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Cloud Pioneers"
        )
        TeamMember.objects.create(team=self.team, user=self.alice)
        TeamMember.objects.create(team=self.team, user=self.bob)
        TeamMember.objects.create(team=self.team, user=self.charlie)

        self.deliverable = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.alice,
            title="Microservice Topology Map",
            link="https://lucid.app/topology-e2e",
            description="Distributed microservice network diagram"
        )

        self.claim_bob = DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.bob,
            contribution_area="Defined Service Mesh & Envoy Routes",
            status='PENDING'
        )
        self.claim_charlie = DeliverableContribution.objects.create(
            deliverable=self.deliverable,
            student=self.charlie,
            contribution_area="Created Kafka Event Topology",
            status='PENDING'
        )

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

    def _logout(self):
        try:
            logout_btn = self.driver.find_element(By.XPATH, "//form[contains(@action, '/logout')]//button")
            logout_btn.click()
            self.wait.until(lambda d: "/login" in d.current_url or "/dashboard" not in d.current_url)
        except Exception:
            self.driver.get(f"{self.live_server_url}/accounts/logout/")

    def test_e2e_claim_verification_and_rejection_browser_flow(self):
        """Live browser workflow:
        1. Bob logs in -> sees pending claim banner -> clicks Verify -> badge updates to Verified on team progress.
        2. Charlie logs in -> sees pending claim banner -> clicks Reject -> badge updates to Rejected on team progress.
        """
        dashboard_url = f"{self.live_server_url}/academic/student/dashboard/"
        progress_url = f"{self.live_server_url}/academic/student/team/{self.team.team_id}/progress/"

        # --- PART 1: BOB VERIFIES HIS CLAIM ---
        self._login("bob_cv_e2e@test.com", "password123")
        self.driver.get(dashboard_url)

        # Confirm pending verification alert
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(., 'Pending Verifications')]")))
        dash_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Microservice Topology Map", dash_text)
        self.assertIn("Defined Service Mesh & Envoy Routes", dash_text)

        # Click Verify button
        verify_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Verify')]")))
        verify_btn.click()

        # Success message displayed and banner cleared
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Verified contribution for')]")))
        dash_text_after = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertNotIn("Action Required: Pending Verifications", dash_text_after)

        # Check Team Progress page for Verified badge
        self.driver.get(progress_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h4[contains(text(), 'Microservice Topology Map')]")))
        prog_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Bob Verifier", prog_text)
        self.assertIn("Defined Service Mesh & Envoy Routes", prog_text)
        self.assertIn("Verified", prog_text)

        self._logout()

        # --- PART 2: CHARLIE REJECTS HIS CLAIM ---
        self._login("charlie_cv_e2e@test.com", "password123")
        self.driver.get(dashboard_url)

        # Confirm pending verification alert for Charlie
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(., 'Pending Verifications')]")))
        charlie_dash_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Microservice Topology Map", charlie_dash_text)
        self.assertIn("Created Kafka Event Topology", charlie_dash_text)

        # Click Reject button
        reject_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Reject')]")))
        reject_btn.click()

        # Success message displayed and banner cleared
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Rejected contribution for')]")))
        charlie_dash_text_after = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertNotIn("Action Required: Pending Verifications", charlie_dash_text_after)

        # Check Team Progress page for Rejected badge
        self.driver.get(progress_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h4[contains(text(), 'Microservice Topology Map')]")))
        prog_text_2 = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Charlie Rejector", prog_text_2)
        self.assertIn("Created Kafka Event Topology", prog_text_2)
        self.assertIn("Rejected", prog_text_2)

