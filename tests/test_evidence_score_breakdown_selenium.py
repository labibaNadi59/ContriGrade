import os
import sys
from datetime import timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from academic.models import (
    Course, CourseSection, Project, Team, TeamMember,
    NonCodingDeliverable, DeliverableContribution,
    EvaluationCriterion, PeerEvaluation, PeerEvaluationScore
)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


import time

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class EvidenceScoreBreakdownSeleniumTests(StaticLiveServerTestCase):
    """
    Selenium UI tests for contribution evidence and score breakdown.
    Acceptance criteria: Selenium verifies that instructors can open the score
    details page and view the evidence and component scores.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        options = Options()
        # Runs with visible browser UI by default so you can watch it automate.
        # Set HEADLESS=1 in environment if headless execution is ever needed.
        if os.environ.get("HEADLESS", "0") == "1":
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1280,850")
        options.add_argument("--log-level=3")

        service = Service(ChromeDriverManager().install())
        cls.driver = webdriver.Chrome(service=service, options=options)
        cls.wait = WebDriverWait(cls.driver, 15)

    @classmethod
    def tearDownClass(cls):
        if cls.driver:
            cls.driver.quit()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.coordinator = User.objects.create_user(
            email="coord_ui@test.com",
            name="Coordinator Vance",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_ui@test.com",
            name="Dr. Ada Lovelace",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_alice = User.objects.create_user(
            email="alice_ui@test.com",
            name="Alice Walker",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob = User.objects.create_user(
            email="bob_ui@test.com",
            name="Bob Smith",
            role=User.Role.STUDENT,
            password="password123"
        )

        course = Course.objects.create(course_code="CSE420", course_name="Cloud Architecture", coordinator=self.coordinator)
        section = CourseSection.objects.create(course=course, section_name="A1", instructor=self.instructor)
        section.students.add(self.student_alice, self.student_bob)

        self.project = Project.objects.create(
            section=section,
            title="Enterprise Cloud Platform",
            deadline=timezone.now() + timedelta(days=14),
            weight_github=0,
            weight_deliverables=50,
            weight_peer=50
        )
        self.team = Team.objects.create(project=self.project, team_name="Alpha Squad")
        TeamMember.objects.create(team=self.team, user=self.student_alice, role_in_team="Lead Architect")
        TeamMember.objects.create(team=self.team, user=self.student_bob, role_in_team="Backend Dev")

        # Deliverable: Alice and Bob each have 1 verified deliverable (team avg=1.0 -> (1/1)*80 = 80.0%)
        d1 = NonCodingDeliverable.objects.create(
            team=self.team, submitted_by=self.student_alice,
            title="System Architecture Blueprint", link="https://docs.alpha.io/arch"
        )
        DeliverableContribution.objects.create(
            deliverable=d1, student=self.student_alice,
            contribution_area="API & Database Schema", status='VERIFIED'
        )
        d2 = NonCodingDeliverable.objects.create(
            team=self.team, submitted_by=self.student_bob,
            title="Security Audit", link="https://docs.alpha.io/sec"
        )
        DeliverableContribution.objects.create(
            deliverable=d2, student=self.student_bob,
            contribution_area="Threat Modeling", status='VERIFIED'
        )

        # Peer Evaluation: Bob rates Alice 4/5 (80.0%)
        crit = EvaluationCriterion.objects.create(project=self.project, name="Technical Leadership", max_score=5)
        eval_ba = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_bob, evaluatee=self.student_alice)
        PeerEvaluationScore.objects.create(evaluation=eval_ba, criterion=crit, score=4)

        self.evidence_path = reverse('student_evidence_detail', kwargs={'team_id': self.team.pk, 'student_id': self.student_alice.pk})
        self.team_scores_path = reverse('team_contribution_scores', kwargs={'team_id': self.team.pk})

    def _login(self, email, password="password123"):
        self.driver.delete_all_cookies()
        self.driver.get(f"{self.live_server_url}/accounts/login/")
        user_input = self.wait.until(EC.presence_of_element_located((By.NAME, "username")))
        pass_input = self.driver.find_element(By.NAME, "password")
        user_input.clear()
        user_input.send_keys(email)
        pass_input.clear()
        pass_input.send_keys(password)
        self.driver.find_element(By.XPATH, "//button[@type='submit']").click()
        self.wait.until(lambda d: "/accounts/login/" not in d.current_url)

    # -------------------------------------------------------------------------
    # TEST 1: Instructor opens evidence page directly and views scores
    # -------------------------------------------------------------------------
    def test_instructor_opens_evidence_page_directly_and_views_scores(self):
        """Instructor navigates directly to score details page and views score breakdown & components."""
        self._login("inst_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.evidence_path}")

        # Verify page header and student title
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(text(), 'Consolidated Assessment')]")))
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Alice Walker", body_text)
        self.assertIn("Alpha Squad", body_text)

        # Verify Calculated Total and component scores
        self.assertIn("Recommended Score", self.driver.page_source)
        self.assertIn("80.0%", body_text)
        self.assertIn("Verified Tasks", body_text)
        self.assertIn("Peer Ratings", body_text)

    # -------------------------------------------------------------------------
    # TEST 2: Instructor navigates from team scores via 'View Evidence' button
    # -------------------------------------------------------------------------
    def test_instructor_navigates_from_team_scores_via_view_evidence_button(self):
        """Instructor opens team scores page and clicks 'View Evidence' button to open student details."""
        self._login("inst_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.team_scores_path}")

        # Locate and click 'View Evidence' button
        view_evidence_btn = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, f"//a[contains(@href, '{self.evidence_path}')]"))
        )
        view_evidence_btn.click()

        # Verify navigation to Alice's evidence page
        self.wait.until(EC.url_contains(self.evidence_path))
        self.assertIn("Consolidated Assessment", self.driver.page_source)

    # -------------------------------------------------------------------------
    # TEST 3: Instructor views verified deliverables evidence
    # -------------------------------------------------------------------------
    def test_instructor_views_deliverable_evidence_details(self):
        """Instructor can review verified non-coding deliverable artifacts and claimed areas."""
        self._login("inst_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.evidence_path}")
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h3[contains(., 'Verified Tasks')]")))

        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("System Architecture Blueprint", body_text)
        self.assertIn("API & Database Schema", body_text)

    # -------------------------------------------------------------------------
    # TEST 4: Instructor views peer evaluation evidence and anonymity
    # -------------------------------------------------------------------------
    def test_instructor_views_peer_evaluation_scores_and_anonymity(self):
        """Instructor views peer evaluation ratings while reviewer identity remains anonymous."""
        self._login("inst_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.evidence_path}")
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h3[contains(., 'Peer Ratings')]")))

        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Technical Leadership", body_text)
        self.assertIn("4/5", body_text)
        self.assertIn("From: Anonymous Teammate", body_text)
        self.assertNotIn("bob_ui@test.com", body_text)

    # -------------------------------------------------------------------------
    # TEST 5: Back button returns to team contribution scores
    # -------------------------------------------------------------------------
    def test_back_to_team_scores_button_navigation(self):
        """Clicking 'Back to Team Scores' returns instructor to the team scores overview."""
        self._login("inst_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.evidence_path}")

        back_link = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Back to Team Scores')]")))
        back_link.click()

        self.wait.until(EC.url_contains(self.team_scores_path))
        self.assertIn("Contribution Scores", self.driver.page_source)

    # -------------------------------------------------------------------------
    # TEST 6: Student blocked from accessing instructor evidence page
    # -------------------------------------------------------------------------
    def test_student_blocked_from_instructor_evidence_page(self):
        """Students cannot view instructor evidence detail page and are redirected to student dashboard."""
        self._login("alice_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.evidence_path}")

        # Wait until student is redirected to student area
        self.wait.until(EC.url_contains("/academic/student/"))
        self.assertNotIn("Consolidated Assessment", self.driver.page_source)

