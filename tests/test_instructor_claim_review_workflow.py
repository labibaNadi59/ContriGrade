

import os
import sys
from datetime import timedelta

from django.test import TestCase, Client
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from django.contrib.messages import get_messages
from django.urls import reverse

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
class InstructorReviewBaseTestCase(TestCase):
    """Common setup for instructor contribution-claim review tests."""

    def setUp(self):
        super().setUp()
        self.coordinator = User.objects.create_user(
            email="coord_ir@test.com",
            name="Coordinator Vance",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_ir@test.com",
            name="Dr. Aris Thorne",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.admin = User.objects.create_user(
            email="admin_ir@test.com",
            name="Admin System",
            role=User.Role.ADMIN,
            password="password123"
        )
        self.student_alice = User.objects.create_user(
            email="alice_ir@test.com",
            name="Alice Submitter",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob = User.objects.create_user(
            email="bob_ir@test.com",
            name="Bob Verified",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_charlie = User.objects.create_user(
            email="charlie_ir@test.com",
            name="Charlie Rejected",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_diana = User.objects.create_user(
            email="diana_ir@test.com",
            name="Diana Pending",
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
        self.section.students.add(
            self.student_alice, self.student_bob,
            self.student_charlie, self.student_diana
        )

        self.project = Project.objects.create(
            section=self.section,
            title="Distributed Microservices Platform",
            description="Term project building scalable architecture",
            deadline=timezone.now() + timedelta(days=21)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Cloud Architecture Squad"
        )
        TeamMember.objects.create(team=self.team, user=self.student_alice)
        TeamMember.objects.create(team=self.team, user=self.student_bob)
        TeamMember.objects.create(team=self.team, user=self.student_charlie)
        TeamMember.objects.create(team=self.team, user=self.student_diana)

        # Deliverable 1: Comprehensive design with Verified & Rejected claims
        self.deliv1 = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_alice,
            title="System Architecture and API Specifications",
            link="https://docs.contrigrade.io/arch-spec",
            description="Complete system design documentation including UML diagrams and OpenAPI 3.0 schema definitions."
        )
        self.claim_bob_verified = DeliverableContribution.objects.create(
            deliverable=self.deliv1,
            student=self.student_bob,
            contribution_area="Auth service architecture and JWT token lifecycle",
            status='VERIFIED'
        )
        self.claim_charlie_rejected = DeliverableContribution.objects.create(
            deliverable=self.deliv1,
            student=self.student_charlie,
            contribution_area="Database sharding and replication topology",
            status='REJECTED'
        )

        # Deliverable 2: Figma UI with Pending claim
        self.deliv2 = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_bob,
            title="Interactive High-Fidelity UI Wireframes",
            link="https://figma.com/file/cloud-ui-mockups",
            description="Interactive client dashboard prototypes and mobile layouts."
        )
        self.claim_diana_pending = DeliverableContribution.objects.create(
            deliverable=self.deliv2,
            student=self.student_diana,
            contribution_area="Design system components and responsive dark mode views",
            status='PENDING'
        )

        self.review_url = f"/academic/instructor/team/{self.team.pk}/deliverables/"


# =====================================================================
# 1. ACCESS CONTROL & ROLE-BASED PERMISSIONS TESTS
# =====================================================================
class InstructorReviewAccessControlTests(InstructorReviewBaseTestCase):
    """Verifies that only authorized academic roles can access the review page."""

    def test_instructor_can_access_team_deliverables_review(self):
        """Instructor can successfully access the deliverables review page."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'academic/team_deliverables.html')

    def test_coordinator_can_access_team_deliverables_review(self):
        """Course coordinator has full access to the deliverables review page."""
        self.client.force_login(self.coordinator)
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)

    def test_admin_can_access_team_deliverables_review(self):
        """System administrator has full access to the deliverables review page."""
        self.client.force_login(self.admin)
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)

    def test_student_access_denied_redirects_with_error_message(self):
        """Students are denied access, redirected to student dashboard with error flash message."""
        self.client.force_login(self.student_alice)
        resp = self.client.get(self.review_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Access denied. Instructor privileges required.", messages)

    def test_unauthenticated_user_redirected_to_login(self):
        """Unauthenticated requests are redirected to the login view."""
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_nonexistent_team_returns_404(self):
        """Accessing deliverables review for an invalid team returns 404."""
        self.client.force_login(self.instructor)
        resp = self.client.get("/academic/instructor/team/999999/deliverables/")
        self.assertEqual(resp.status_code, 404)


# =====================================================================
# 2. CONTRIBUTION EVIDENCE DISPLAY TESTS
# =====================================================================
class InstructorReviewEvidenceDisplayTests(InstructorReviewBaseTestCase):
    """Verifies that instructor can review all contribution evidence and metadata."""

    def test_deliverable_metadata_displayed(self):
        """Instructor sees deliverable title, submitter name, team name, and project title."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        content = resp.content.decode('utf-8')

        self.assertIn("System Architecture and API Specifications", content)
        self.assertIn("Interactive High-Fidelity UI Wireframes", content)
        self.assertIn("Alice Submitter", content)
        self.assertIn("Bob Verified", content)
        self.assertIn("Cloud Architecture Squad", content)
        self.assertIn("Distributed Microservices Platform", content)

    def test_deliverable_resource_links_displayed(self):
        """Instructor sees external resource link button pointing to deliverable artifact."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        content = resp.content.decode('utf-8')

        self.assertIn('href="https://docs.contrigrade.io/arch-spec"', content)
        self.assertIn('href="https://figma.com/file/cloud-ui-mockups"', content)
        self.assertIn("Open Resource", content)

    def test_deliverable_description_narratives_displayed(self):
        """Instructor can read the detailed narrative description provided for deliverables."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        content = resp.content.decode('utf-8')

        self.assertIn("Complete system design documentation including UML diagrams", content)
        self.assertIn("Interactive client dashboard prototypes and mobile layouts.", content)

    def test_claimed_contribution_areas_displayed_per_student(self):
        """Instructor can review the specific contribution area claimed by each teammate."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        content = resp.content.decode('utf-8')

        self.assertIn("Auth service architecture and JWT token lifecycle", content)
        self.assertIn("Database sharding and replication topology", content)
        self.assertIn("Design system components and responsive dark mode views", content)

    def test_deliverable_without_description_omits_narrative_block(self):
        """Deliverable without description renders cleanly without broken markup."""
        deliv_nodesc = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_charlie,
            title="Clean Architecture Blueprint",
            link="https://blueprint.io/clean",
            description=""
        )
        DeliverableContribution.objects.create(
            deliverable=deliv_nodesc,
            student=self.student_alice,
            contribution_area="Core domain models",
            status='VERIFIED'
        )

        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Clean Architecture Blueprint", content)
        self.assertIn("Core domain models", content)

    def test_deliverables_ordered_by_submitted_at_descending(self):
        """Deliverables are presented in descending order of submission timestamp."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        deliverables = list(resp.context['deliverables'])

        self.assertEqual(len(deliverables), 2)
        # deliv2 was created after deliv1
        self.assertEqual(deliverables[0].pk, self.deliv2.pk)
        self.assertEqual(deliverables[1].pk, self.deliv1.pk)


# =====================================================================
# 3. VERIFICATION STATUS BADGES & STYLING TESTS
# =====================================================================
class InstructorReviewVerificationStatusTests(InstructorReviewBaseTestCase):
    """Verifies that verification statuses are correctly presented to the instructor."""

    def test_verified_status_badge_and_styling(self):
        """Verified claim renders 'Verified by Peer' with green badge and check icon."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        content = resp.content.decode('utf-8')

        self.assertIn("Verified by Peer", content)
        self.assertIn("bg-green-100", content)
        self.assertIn("text-green-800", content)
        self.assertIn("fa-check", content)

    def test_rejected_status_badge_and_styling(self):
        """Rejected claim renders 'Rejected by Peer' with red badge and xmark icon."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        content = resp.content.decode('utf-8')

        self.assertIn("Rejected by Peer", content)
        self.assertIn("bg-red-100", content)
        self.assertIn("text-red-800", content)
        self.assertIn("fa-xmark", content)

    def test_pending_status_badge_and_styling(self):
        """Pending claim renders 'Pending Verification' with yellow badge and clock icon."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        content = resp.content.decode('utf-8')

        self.assertIn("Pending Verification", content)
        self.assertIn("bg-yellow-100", content)
        self.assertIn("text-yellow-800", content)
        self.assertIn("fa-clock", content)

    def test_multiple_statuses_on_same_deliverable(self):
        """Single deliverable with multiple tagged contributors accurately reflects disparate statuses."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        deliverables = {d.pk: d for d in resp.context['deliverables']}

        deliv1_obj = deliverables[self.deliv1.pk]
        claims = {c.student.pk: c for c in deliv1_obj.filtered_contributions}

        self.assertEqual(claims[self.student_bob.pk].status, 'VERIFIED')
        self.assertEqual(claims[self.student_charlie.pk].status, 'REJECTED')


# =====================================================================
# 4. STATUS FILTERING WORKFLOW TESTS
# =====================================================================
class InstructorReviewFilterWorkflowTests(InstructorReviewBaseTestCase):
    """Verifies that the instructor can filter contributions by status tab."""

    def test_filter_all_claims(self):
        """status=ALL returns all deliverables with all contribution claims attached."""
        self.client.force_login(self.instructor)
        resp = self.client.get(f"{self.review_url}?status=ALL")
        self.assertEqual(resp.status_code, 200)

        deliverables = resp.context['deliverables']
        self.assertEqual(len(deliverables), 2)
        self.assertEqual(resp.context['current_filter'], 'ALL')

    def test_filter_pending_claims(self):
        """status=PENDING returns only deliverables with pending claims attached."""
        self.client.force_login(self.instructor)
        resp = self.client.get(f"{self.review_url}?status=PENDING")
        self.assertEqual(resp.status_code, 200)

        deliverables = resp.context['deliverables']
        self.assertEqual(len(deliverables), 1)
        self.assertEqual(deliverables[0].pk, self.deliv2.pk)
        self.assertEqual(len(deliverables[0].filtered_contributions), 1)
        self.assertEqual(deliverables[0].filtered_contributions[0].status, 'PENDING')
        self.assertEqual(deliverables[0].filtered_contributions[0].student, self.student_diana)

        content = resp.content.decode('utf-8')
        self.assertIn("Pending Verification", content)
        self.assertNotIn("Verified by Peer", content)
        self.assertNotIn("Rejected by Peer", content)

    def test_filter_verified_claims(self):
        """status=VERIFIED returns only deliverables with verified claims attached."""
        self.client.force_login(self.instructor)
        resp = self.client.get(f"{self.review_url}?status=VERIFIED")
        self.assertEqual(resp.status_code, 200)

        deliverables = resp.context['deliverables']
        self.assertEqual(len(deliverables), 1)
        self.assertEqual(deliverables[0].pk, self.deliv1.pk)
        self.assertEqual(len(deliverables[0].filtered_contributions), 1)
        self.assertEqual(deliverables[0].filtered_contributions[0].status, 'VERIFIED')
        self.assertEqual(deliverables[0].filtered_contributions[0].student, self.student_bob)

        content = resp.content.decode('utf-8')
        self.assertIn("Verified by Peer", content)
        self.assertNotIn("Pending Verification", content)

    def test_filter_rejected_claims(self):
        """status=REJECTED returns only deliverables with rejected claims attached."""
        self.client.force_login(self.instructor)
        resp = self.client.get(f"{self.review_url}?status=REJECTED")
        self.assertEqual(resp.status_code, 200)

        deliverables = resp.context['deliverables']
        self.assertEqual(len(deliverables), 1)
        self.assertEqual(deliverables[0].pk, self.deliv1.pk)
        self.assertEqual(len(deliverables[0].filtered_contributions), 1)
        self.assertEqual(deliverables[0].filtered_contributions[0].status, 'REJECTED')
        self.assertEqual(deliverables[0].filtered_contributions[0].student, self.student_charlie)

        content = resp.content.decode('utf-8')
        self.assertIn("Rejected by Peer", content)
        self.assertNotIn("Pending Verification", content)

    def test_filter_empty_state_when_no_matching_claims(self):
        """Filter resulting in 0 matches displays helpful empty state banner."""
        # Remove pending claim
        self.claim_diana_pending.delete()

        self.client.force_login(self.instructor)
        resp = self.client.get(f"{self.review_url}?status=PENDING")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['deliverables']), 0)

        content = resp.content.decode('utf-8')
        self.assertIn("No Deliverables Found", content)
        self.assertIn('There are no peer review claims matching the "PENDING" filter', content)

    def test_team_without_any_deliverables_displays_empty_state(self):
        """Team with zero deliverables displays empty state cleanly."""
        team_empty = Team.objects.create(
            project=self.project,
            team_name="Empty Team"
        )
        self.client.force_login(self.instructor)
        resp = self.client.get(f"/academic/instructor/team/{team_empty.pk}/deliverables/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("No Deliverables Found", content)

    def test_navigation_sidebar_links_between_analytics_and_peer_reviews(self):
        """Sidebar provides links between Code Analytics and Peer Reviews."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.review_url)
        content = resp.content.decode('utf-8')

        analytics_url = f"/academic/instructor/team/{self.team.pk}/analytics/"
        self.assertIn(analytics_url, content)
        self.assertIn("Code Analytics", content)
        self.assertIn("Peer Reviews", content)


# =====================================================================
# 5. LIVE SELENIUM BROWSER E2E TESTS (HEADLESS CHROME)
# =====================================================================
class InstructorReviewSeleniumE2ETests(StaticLiveServerTestCase):
    """End-to-end browser tests verifying evidence review and verification statuses."""

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
            email="coord_se_ir@test.com",
            name="Coord SE",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_se_ir@test.com",
            name="Dr. Sarah Jenkins",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_lead = User.objects.create_user(
            email="lead_se_ir@test.com",
            name="Alex Lead",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob = User.objects.create_user(
            email="bob_se_ir@test.com",
            name="Bob Verified",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_charlie = User.objects.create_user(
            email="charlie_se_ir@test.com",
            name="Charlie Rejected",
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
        self.section.students.add(self.student_lead, self.student_bob, self.student_charlie)

        self.project = Project.objects.create(
            section=self.section,
            title="E2E Architecture Project",
            description="Testing live instructor review",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Pioneer Engineers"
        )
        TeamMember.objects.create(team=self.team, user=self.student_lead)
        TeamMember.objects.create(team=self.team, user=self.student_bob)
        TeamMember.objects.create(team=self.team, user=self.student_charlie)

        self.deliv = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_lead,
            title="Cloud Infrastructure Specification",
            link="https://terraform.contrigrade.io/infra-spec",
            description="Terraform architecture blueprints and disaster recovery plans."
        )
        self.claim_bob = DeliverableContribution.objects.create(
            deliverable=self.deliv,
            student=self.student_bob,
            contribution_area="VPC peering and security group configuration",
            status='VERIFIED'
        )
        self.claim_charlie = DeliverableContribution.objects.create(
            deliverable=self.deliv,
            student=self.student_charlie,
            contribution_area="Kubernetes ingress and cert-manager",
            status='REJECTED'
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

    def test_e2e_instructor_reviews_evidence_and_statuses(self):
        """End-to-end browser review flow:
        1. Instructor logs in.
        2. Navigates to Peer Reviews page for team.
        3. Reviews evidence: deliverable title, submitter, link, description, claimed areas.
        4. Reviews status badges: Verified by Peer, Rejected by Peer.
        5. Tests quick filters: Verified, Rejected, Pending, All Claims.
        """
        review_url = f"{self.live_server_url}/academic/instructor/team/{self.team.pk}/deliverables/"

        # 1. Login as instructor
        self._login("inst_se_ir@test.com", "password123")

        # 2. Navigate to Deliverables & Peer Reviews page
        self.driver.get(review_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(text(), 'Deliverables & Peer Reviews')]")))

        # 3. Review deliverable evidence
        page_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Cloud Infrastructure Specification", page_text)
        self.assertIn("Alex Lead", page_text)
        self.assertIn("Terraform architecture blueprints and disaster recovery plans.", page_text)
        self.assertIn("VPC peering and security group configuration", page_text)
        self.assertIn("Kubernetes ingress and cert-manager", page_text)

        # Check Open Resource link
        link_el = self.driver.find_element(By.XPATH, "//a[contains(., 'Open Resource')]")
        self.assertEqual(link_el.get_attribute("href"), "https://terraform.contrigrade.io/infra-spec")

        # 4. Review verification statuses
        self.assertIn("Verified by Peer", page_text)
        self.assertIn("Rejected by Peer", page_text)

        # 5. Test Quick Filters via UI clicks
        # Click Verified filter tab
        verified_tab = self.driver.find_element(By.XPATH, "//a[contains(., 'Verified')]")
        verified_tab.click()
        self.wait.until(lambda d: "status=VERIFIED" in d.current_url)
        verified_page_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Verified by Peer", verified_page_text)
        self.assertNotIn("Rejected by Peer", verified_page_text)

        # Click Rejected filter tab
        rejected_tab = self.driver.find_element(By.XPATH, "//a[contains(., 'Rejected')]")
        rejected_tab.click()
        self.wait.until(lambda d: "status=REJECTED" in d.current_url)
        rejected_page_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Rejected by Peer", rejected_page_text)
        self.assertNotIn("Verified by Peer", rejected_page_text)

        # Click Pending filter tab (should show empty state)
        pending_tab = self.driver.find_element(By.XPATH, "//a[contains(., 'Pending')]")
        pending_tab.click()
        self.wait.until(lambda d: "status=PENDING" in d.current_url)
        pending_page_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("No Deliverables Found", pending_page_text)

        # Click All Claims filter tab
        all_tab = self.driver.find_element(By.XPATH, "//a[contains(., 'All Claims')]")
        all_tab.click()
        self.wait.until(lambda d: "status=ALL" in d.current_url)
        all_page_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Verified by Peer", all_page_text)
        self.assertIn("Rejected by Peer", all_page_text)

