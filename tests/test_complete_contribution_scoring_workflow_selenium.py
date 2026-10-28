import os
import sys
import time
from datetime import timedelta

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from accounts.models import User
from academic.models import (
    Course, CourseSection, Project, Team, TeamMember,
    NonCodingDeliverable, DeliverableContribution,
    EvaluationCriterion, PeerEvaluation, PeerEvaluationScore
)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CompleteContributionScoringWorkflowSeleniumTests(StaticLiveServerTestCase):
    """
    Selenium test for the complete contribution scoring workflow.
    Acceptance criteria: Instructor can calculate and view contribution score
    recommendations using configured weights and available evidence.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        options = Options()
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1280,850")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--log-level=3")

        cls.driver = webdriver.Chrome(options=options)
        cls.wait = WebDriverWait(cls.driver, 15)

    @classmethod
    def tearDownClass(cls):
        if cls.driver:
            cls.driver.quit()
        super().tearDownClass()

    def tearDown(self):
        super().tearDown()
        self.driver.delete_all_cookies()

    def setUp(self):
        super().setUp()
        self.coordinator = User.objects.create_user(
            email="coord_sel_score@test.com",
            name="Coord Scoring",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_sel_score@test.com",
            name="Prof. Scoring Workflow",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.student_alice = User.objects.create_user(
            email="alice_sel_score@test.com",
            name="Alice Wonder",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob = User.objects.create_user(
            email="bob_sel_score@test.com",
            name="Bob Builder",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE405",
            course_name="Real-Time Systems",
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
            title="Real-Time Drone OS",
            deadline=timezone.now() + timedelta(days=20),
            weight_github=0,
            weight_deliverables=50,
            weight_peer=50
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="SkyNav Team"
        )
        TeamMember.objects.create(team=self.team, user=self.student_alice, role_in_team="Scheduler Lead")
        TeamMember.objects.create(team=self.team, user=self.student_bob, role_in_team="Driver Dev")

        # Deliverables evidence
        d1 = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_alice,
            title="Telemetry Architecture",
            link="https://docs.drone.io/arch"
        )
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_alice, contribution_area="Scheduler", status='VERIFIED')
        DeliverableContribution.objects.create(deliverable=d1, student=self.student_bob, contribution_area="Actuators", status='VERIFIED')

        # Peer evaluation evidence
        crit = EvaluationCriterion.objects.create(project=self.project, name="Technical Contribution", max_score=5)
        pe_alice = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_bob, evaluatee=self.student_alice)
        PeerEvaluationScore.objects.create(evaluation=pe_alice, criterion=crit, score=5)

        pe_bob = PeerEvaluation.objects.create(team=self.team, evaluator=self.student_alice, evaluatee=self.student_bob)
        PeerEvaluationScore.objects.create(evaluation=pe_bob, criterion=crit, score=4)

        self.scores_path = reverse('team_contribution_scores', kwargs={'team_id': self.team.pk})

    def _login(self, email, password):
        self.driver.delete_all_cookies()
        self.driver.get(f"{self.live_server_url}/accounts/login/")
        user_field = self.wait.until(EC.presence_of_element_located((By.NAME, "username")))
        pass_field = self.driver.find_element(By.NAME, "password")
        submit_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")

        user_field.clear()
        user_field.send_keys(email)
        pass_field.clear()
        pass_field.send_keys(password)
        submit_btn.click()
        self.wait.until(EC.url_changes(f"{self.live_server_url}/accounts/login/"))
        time.sleep(0.5)

    def test_01_instructor_navigates_to_contribution_scores_page(self):
        """Selenium verifies instructor can navigate to team contribution scores dashboard."""
        self._login("inst_sel_score@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.scores_path}")

        heading = self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(., 'Team Contribution Scores')]")))
        self.assertIsNotNone(heading)
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Real-Time Drone OS", body_text)
        self.assertIn("SkyNav Team", body_text)

    def test_02_scores_page_displays_individual_recommendations(self):
        """Selenium verifies individual calculated score recommendations are rendered for students."""
        self._login("inst_sel_score@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.scores_path}")

        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Alice Wonder')]")))
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Alice Wonder", body_text)
        self.assertIn("Bob Builder", body_text)
        self.assertIn("%", body_text)

    def test_03_scores_page_displays_component_evidence(self):
        """Selenium verifies component evidence metrics (Deliverables, Peer Eval) are displayed."""
        self._login("inst_sel_score@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.scores_path}")

        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Deliverables')]")))
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Deliverables", body_text)
        self.assertIn("Peer Eval", body_text)

    def test_04_recalculate_action_refreshes_scores(self):
        """Selenium verifies clicking Recalculate triggers score refresh and preserves display."""
        self._login("inst_sel_score@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.scores_path}")

        recalc_link = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Recalculate')]")))
        recalc_link.click()
        time.sleep(1)

        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(., 'Team Contribution Scores')]")))
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Alice Wonder", body_text)

    def test_05_weight_change_updates_displayed_scores(self):
        """Selenium verifies updating weights updates score calculation display in browser."""
        # Change weights to 70% Deliverables, 30% Peer
        self.project.weight_deliverables = 70
        self.project.weight_peer = 30
        self.project.save()

        self._login("inst_sel_score@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.scores_path}")

        body_text = self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body"))).text
        self.assertIn("Weight: 70%", body_text)
        self.assertIn("Weight: 30%", body_text)

    def test_06_navigate_to_student_evidence_detail_from_scores(self):
        """Selenium verifies instructor can navigate from scores page to detailed student evidence."""
        self._login("inst_sel_score@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.scores_path}")

        review_link = self.wait.until(EC.element_to_be_clickable((
            By.XPATH, f"//a[contains(@href, '/student/{self.student_alice.pk}/evidence/')]"
        )))
        self.driver.execute_script("arguments[0].scrollIntoView(true);", review_link)
        time.sleep(0.3)
        review_link.click()
        time.sleep(1)

        body_text = self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body"))).text
        self.assertIn("Alice Wonder", body_text)
        self.assertIn("SkyNav Team", body_text)
