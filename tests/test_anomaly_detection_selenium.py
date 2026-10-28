
import os
import sys
from datetime import timedelta
import time

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


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AnomalyDetectionSeleniumTests(StaticLiveServerTestCase):
    """
    Selenium UI tests for anomaly flags and explanations.
    Acceptance criteria: Selenium verifies that instructors can view
    anomaly flags and their explanations across team scores and evidence pages.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        options = Options()
        # Runs with visible browser UI so the user can watch the automation live on screen
        options.add_argument("--window-size=1280,850")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
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
        # 1. Users
        self.instructor = User.objects.create_user(
            email="inst_ui@test.com",
            name="Dr. Alan Turing",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.coordinator = User.objects.create_user(
            email="coord_ui@test.com",
            name="Coord Grace",
            role=User.Role.COORDINATOR,
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

        # 2. Academic Setup
        course = Course.objects.create(course_code="CSE460", course_name="Distributed Cloud Systems", coordinator=self.coordinator)
        section = CourseSection.objects.create(course=course, section_name="Sec A", instructor=self.instructor)
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

        # 3. Evidence Setup:
        # Alice and Bob both have 2 verified deliverables (deliverables score = 80% each)
        d1 = NonCodingDeliverable.objects.create(team=self.team, submitted_by=self.student_alice, title="System Architecture Blueprint", link="https://docs.alpha.io/arch")
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_alice, contribution_area="Architecture", status='VERIFIED')
        d2 = NonCodingDeliverable.objects.create(team=self.team, submitted_by=self.student_alice, title="Database Migration Schema", link="https://docs.alpha.io/db")
        DeliverableContribution.objects.create(deliverable=d2, student=self.student_alice, contribution_area="Schema", status='VERIFIED')

        d3 = NonCodingDeliverable.objects.create(team=self.team, submitted_by=self.student_bob, title="API Gateway Config", link="https://docs.alpha.io/api")
        DeliverableContribution.objects.create(deliverable=d3, student=self.student_bob, contribution_area="Gateway", status='VERIFIED')
        d4 = NonCodingDeliverable.objects.create(team=self.team, submitted_by=self.student_bob, title="Security Threat Audit", link="https://docs.alpha.io/sec")
        DeliverableContribution.objects.create(deliverable=d4, student=self.student_bob, contribution_area="Security", status='VERIFIED')

        # 4. Peer Evaluations:
        # Bob harshly rates Alice 1/5 (20.0%) -> creates a 60% gap (80% - 20% >= 35%), triggering Rule C (Peer Deficit) for Alice
        crit = EvaluationCriterion.objects.create(project=self.project, name="Technical Leadership", max_score=5)
        eval_b_to_a = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_bob, evaluatee=self.student_alice)
        PeerEvaluationScore.objects.create(evaluation=eval_b_to_a, criterion=crit, score=1)

        # Alice rates Bob fairly 4/5 (80.0%) -> 80% deliverables vs 80% peer review -> Bob has 0 anomalies (Clean)
        eval_a_to_b = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_alice, evaluatee=self.student_bob)
        PeerEvaluationScore.objects.create(evaluation=eval_a_to_b, criterion=crit, score=4)

        self.team_scores_path = reverse('team_contribution_scores', kwargs={'team_id': self.team.pk})
        self.alice_evidence_path = reverse('student_evidence_detail', kwargs={'team_id': self.team.pk, 'student_id': self.student_alice.pk})
        self.bob_evidence_path = reverse('student_evidence_detail', kwargs={'team_id': self.team.pk, 'student_id': self.student_bob.pk})

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
    # TEST 1: Instructor views anomaly summary metric card on team scores page
    # -------------------------------------------------------------------------
    def test_01_instructor_views_anomaly_summary_card_on_team_scores_page(self):
        """Instructor opens team scores page and verifies the summary metric card displays anomaly count & 'Flagged' badge."""
        self._login("inst_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.team_scores_path}")

        # Locate 'Detected Anomalies' metric block
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//p[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'detected anomalies')]")))
        time.sleep(1)
        body_text = self.driver.find_element(By.TAG_NAME, "body").text

        self.assertIn("detected anomalies", body_text.lower())
        self.assertIn("flagged", body_text.lower())
        self.assertIn("Alpha Squad", body_text)

    # -------------------------------------------------------------------------
    # TEST 2: Instructor views flagged student badge on team scores card
    # -------------------------------------------------------------------------
    def test_02_instructor_views_flagged_student_badge_on_team_scores_page(self):
        """Instructor verifies that the flagged student's card shows the warning badge indicator."""
        self._login("inst_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.team_scores_path}")

        # Wait for Alice's card to load
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h3[contains(text(), 'Alice Walker')]")))
        time.sleep(1)
        page_source = self.driver.page_source

        # Verify badge icon and anomaly count indicator
        self.assertIn("anomaly pattern(s) detected", page_source)
        self.assertIn("fa-triangle-exclamation", page_source)

    # -------------------------------------------------------------------------
    # TEST 3: Instructor views anomaly explanation in student card footer
    # -------------------------------------------------------------------------
    def test_03_instructor_views_anomaly_explanation_card_in_student_card_footer(self):
        """Instructor verifies the anomaly title, category, and explanation render in the card footer."""
        self._login("inst_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.team_scores_path}")

        self.wait.until(EC.presence_of_element_located((By.XPATH, "//span[contains(text(), 'Peer Rating Deficit')]")))
        time.sleep(1)
        body_text = self.driver.find_element(By.TAG_NAME, "body").text

        # Verify anomaly title, category, and explanation
        self.assertIn("Peer Rating Deficit (High Output vs. Low Peer Score)", body_text)
        self.assertIn("cross-pillar mismatch", body_text.lower())
        self.assertIn("teammates rated them significantly lower", body_text)

    # -------------------------------------------------------------------------
    # TEST 4: Instructor navigates to student evidence detail and views anomaly banner
    # -------------------------------------------------------------------------
    def test_04_instructor_navigates_to_student_evidence_and_views_anomaly_banner(self):
        """Instructor clicks 'View Evidence' on flagged student and reviews the detailed anomaly banner."""
        self._login("inst_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.team_scores_path}")
        time.sleep(1)

        # Click Alice's 'View Evidence' button
        view_evidence_btn = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, f"//a[contains(@href, '{self.alice_evidence_path}')]"))
        )
        view_evidence_btn.click()

        # Wait for evidence detail page
        self.wait.until(EC.url_contains(self.alice_evidence_path))
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h3[contains(text(), 'Detected Contribution Anomalies')]")))
        time.sleep(1)

        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Detected Contribution Anomalies (1)", body_text)
        self.assertIn("Verify in Viva", body_text)
        self.assertIn("Peer Rating Deficit (High Output vs. Low Peer Score)", body_text)
        self.assertIn("cross-pillar mismatch", body_text.lower())

    # -------------------------------------------------------------------------
    # TEST 5: Instructor views 'Verified Clean' banner for student without anomalies
    # -------------------------------------------------------------------------
    def test_05_instructor_views_verified_clean_status_for_student_without_anomalies(self):
        """Instructor opens clean student's page and verifies 'Verified Clean' status without anomaly warnings."""
        self._login("inst_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.bob_evidence_path}")

        # Verify clean banner elements
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h3[contains(text(), 'No Unusual Contribution Patterns Detected')]")))
        time.sleep(1)
        body_text = self.driver.find_element(By.TAG_NAME, "body").text

        self.assertIn("No Unusual Contribution Patterns Detected", body_text)
        self.assertIn("Verified Clean", body_text)
        self.assertNotIn("Review Recommended", body_text)
        self.assertNotIn("Detected Contribution Anomalies", body_text)

    # -------------------------------------------------------------------------
    # TEST 6: Student blocked from instructor anomaly views
    # -------------------------------------------------------------------------
    def test_06_student_blocked_from_instructor_anomaly_views(self):
        """Students cannot view instructor anomaly detail pages and are redirected to student area."""
        self._login("alice_ui@test.com")
        self.driver.get(f"{self.live_server_url}{self.alice_evidence_path}")

        # Wait until student is redirected away from instructor view
        self.wait.until(EC.url_contains("/academic/student/"))
        time.sleep(1)
        self.assertNotIn("Contribution Evidence", self.driver.page_source)

