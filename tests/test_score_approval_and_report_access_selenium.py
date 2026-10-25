
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
    EvaluationCriterion, PeerEvaluation, PeerEvaluationScore,
    FinalAssessment
)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ScoreApprovalAndReportAccessSeleniumTests(StaticLiveServerTestCase):
    """
    Live browser Selenium UI tests for score approval and report access.
    Selenium verifies score approval, report generation, and access restrictions
    through the user interface in a visible Chrome browser.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        options = Options()
        # Explicitly NO headless mode - visibly opens browser window for testing
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

        # 1. Users
        self.instructor = User.objects.create_user(
            email="inst_sel_approval@test.com",
            name="Prof. Donald Knuth",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.coordinator = User.objects.create_user(
            email="coord_sel_approval@test.com",
            name="Coord Grace Hopper",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.student_alice = User.objects.create_user(
            email="alice_sel_app@test.com",
            name="Alice Smith",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob = User.objects.create_user(
            email="bob_sel_app@test.com",
            name="Bob Jones",
            role=User.Role.STUDENT,
            password="password123"
        )

        # 2. Academic structure
        self.course = Course.objects.create(
            course_code="CSE498",
            course_name="Distributed Consensus Lab",
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
            weight_deliverables=50,
            weight_peer=50
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Alpha Consensus"
        )
        TeamMember.objects.create(team=self.team, user=self.student_alice, role_in_team="Lead Architect")
        TeamMember.objects.create(team=self.team, user=self.student_bob, role_in_team="Core Developer")

        # 3. Evidence
        d1 = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_alice,
            title="Raft Algorithm Specification",
            link="https://docs.alpha.io/raft"
        )
        DeliverableContribution.objects.create(
            deliverable=d1,
            student=self.student_alice,
            contribution_area="Leader Election",
            status='VERIFIED'
        )

        d2 = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_bob,
            title="State Machine Replication",
            link="https://docs.alpha.io/sm"
        )
        DeliverableContribution.objects.create(
            deliverable=d2,
            student=self.student_bob,
            contribution_area="Log Consistency",
            status='VERIFIED'
        )

        crit = EvaluationCriterion.objects.create(
            project=self.project,
            name="Technical Contribution",
            max_score=5
        )
        pe = PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.student_bob,
            evaluatee=self.student_alice,
            general_feedback="Superb consensus design."
        )
        PeerEvaluationScore.objects.create(evaluation=pe, criterion=crit, score=5)

        # URLs
        self.team_scores_path = reverse('team_contribution_scores', kwargs={'team_id': self.team.pk})
        self.team_report_path = reverse('team_assessment_report', kwargs={'team_id': self.team.pk})
        self.project_report_path = reverse('project_assessment_report', kwargs={'project_id': self.project.pk})
        self.reports_hub_path = reverse('reports_hub')

    def _login(self, email, password):
        """Helper to log in as any role via the visible browser."""
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

    # -------------------------------------------------------------------------
    # TEST 1: Single Student Score Approval and Toggle via Live UI
    # -------------------------------------------------------------------------
    def test_01_ui_single_student_approval_toggle(self):
        """Selenium verifies instructor can approve an individual student score and toggle it to unlock."""
        self._login("inst_sel_approval@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.team_scores_path}")

        # 1. Locate Alice's single approve button and click it
        approve_btn = self.wait.until(EC.presence_of_element_located((
            By.XPATH, f"//input[@name='student_id' and @value='{self.student_alice.user_id}']/following-sibling::button"
        )))
        self.driver.execute_script("arguments[0].scrollIntoView(true);", approve_btn)
        time.sleep(0.5)
        approve_btn.click()
        time.sleep(1)

        # 2. Verify Alice's card updates to "Approved Final Score"
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//span[contains(., 'Approved Final Score')]")))
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Approved Final Score", body_text)
        self.assertIn("1/2", body_text)

        # Verify DB persistence
        fa = FinalAssessment.objects.get(project=self.project, student=self.student_alice)
        self.assertTrue(fa.is_approved)
        self.assertEqual(fa.approved_by, self.instructor)
        time.sleep(0.8)

        # 3. Click again to toggle approval off (unlock)
        unlock_btn = self.wait.until(EC.presence_of_element_located((
            By.XPATH, f"//input[@name='student_id' and @value='{self.student_alice.user_id}']/following-sibling::button"
        )))
        self.driver.execute_script("arguments[0].scrollIntoView(true);", unlock_btn)
        time.sleep(0.5)
        unlock_btn.click()
        time.sleep(1)

        # 4. Verify status reverts to "Pending Approval"
        fa.refresh_from_db()
        self.assertFalse(fa.is_approved)
        self.assertIsNone(fa.approved_by)

    # -------------------------------------------------------------------------
    # TEST 2: Bulk Team Score Approval via Live UI
    # -------------------------------------------------------------------------
    def test_02_ui_bulk_team_score_approval(self):
        """Selenium verifies instructor can bulk approve all scores for an entire team."""
        self._login("inst_sel_approval@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.team_scores_path}")

        # 1. Locate and click "Approve All Scores" button
        bulk_btn = self.wait.until(EC.presence_of_element_located((
            By.XPATH, "//input[@name='action' and @value='approve_all_team']/following-sibling::button"
        )))
        self.driver.execute_script("arguments[0].scrollIntoView(true);", bulk_btn)
        time.sleep(0.5)
        bulk_btn.click()
        time.sleep(1)

        # 2. Verify success banner and that all cards are approved
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//span[contains(., 'Approved Final Score')]")))
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("All final scores for Alpha Consensus have been officially approved", body_text)
        self.assertIn("Re-Approve All (2/2)", body_text)

        # Verify database: both students are approved
        self.assertEqual(FinalAssessment.objects.filter(project=self.project, is_approved=True).count(), 2)
        time.sleep(1)

    # -------------------------------------------------------------------------
    # TEST 3: Navigate from Team Scores to Official Assessment Report
    # -------------------------------------------------------------------------
    def test_03_ui_navigate_to_assessment_report(self):
        """Selenium verifies clicking Assessment Report navigates to official report layout."""
        self._login("inst_sel_approval@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.team_scores_path}")

        # Locate Assessment Report navigation link
        report_link = self.wait.until(EC.presence_of_element_located((
            By.XPATH, "//a[contains(., 'Assessment Report')]"
        )))
        self.driver.execute_script("arguments[0].scrollIntoView(true);", report_link)
        time.sleep(0.5)
        report_link.click()
        time.sleep(1)

        # Verify Report view elements
        heading = self.wait.until(EC.presence_of_element_located((
            By.XPATH, "//h2[contains(., 'Official Final Assessment Report')]"
        )))
        self.assertTrue(heading.is_displayed())

        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Consensus Engine Project", body_text)
        self.assertIn("Alpha Consensus", body_text)
        self.assertIn("Alice Smith", body_text)
        self.assertIn("Bob Jones", body_text)
        self.assertIn("Prof. Donald Knuth", body_text)
        time.sleep(1)

    # -------------------------------------------------------------------------
    # TEST 4: Generate and Verify CSV Export Link in Live UI
    # -------------------------------------------------------------------------
    def test_04_ui_report_csv_export_link(self):
        """Selenium verifies Export CSV button points to valid query param and is clickable."""
        self._login("inst_sel_approval@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.team_report_path}")

        csv_btn = self.wait.until(EC.presence_of_element_located((
            By.XPATH, "//a[contains(., 'Export CSV')]"
        )))
        self.assertTrue(csv_btn.is_displayed())
        href = csv_btn.get_attribute("href")
        self.assertIn("?export=csv", href)
        time.sleep(1)

    # -------------------------------------------------------------------------
    # TEST 5: Access Reports Hub and Project-Wide Report in Live UI
    # -------------------------------------------------------------------------
    def test_05_ui_reports_hub_and_project_report(self):
        """Selenium verifies instructor can navigate Reports Hub to launch class-wide assessment reports."""
        self._login("inst_sel_approval@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.reports_hub_path}")

        # 1. Verify Reports Hub renders project card
        heading = self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(., 'Reports Hub')]")))
        self.assertTrue(heading.is_displayed())
        self.assertIn("Consensus Engine Project", self.driver.find_element(By.TAG_NAME, "body").text)

        # 2. Click "Final Assessment Report" for the project
        proj_report_btn = self.wait.until(EC.presence_of_element_located((
            By.XPATH, "//a[contains(., 'Final Assessment Report')]"
        )))
        self.driver.execute_script("arguments[0].scrollIntoView(true);", proj_report_btn)
        time.sleep(0.5)
        proj_report_btn.click()
        time.sleep(1)

        # 3. Verify Project-wide report displays multi-team table
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//th[contains(., 'Team')]")))
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Consensus Engine Project", body_text)
        self.assertIn("Alpha Consensus", body_text)
        time.sleep(1)

    # -------------------------------------------------------------------------
    # TEST 6: Enforce Access Restrictions for Student and Anonymous Users
    # -------------------------------------------------------------------------
    def test_06_ui_access_restrictions_for_students_and_anonymous(self):
        """Selenium verifies students and unauthenticated users are restricted from report views."""
        # 1. Student login -> attempt accessing team assessment report
        self._login("alice_sel_app@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.team_report_path}")
        time.sleep(1)

        # Verify student redirected away to student dashboard
        self.assertIn("/academic/student/", self.driver.current_url)

        # 2. Student attempt accessing Reports Hub
        self.driver.get(f"{self.live_server_url}{self.reports_hub_path}")
        time.sleep(1)
        self.assertIn("/academic/student/", self.driver.current_url)

        # 3. Unauthenticated (anonymous) access -> redirected to login
        self.driver.delete_all_cookies()
        self.driver.get(f"{self.live_server_url}{self.team_report_path}")
        time.sleep(1)
        self.assertIn("/accounts/login/", self.driver.current_url)
        time.sleep(1)

