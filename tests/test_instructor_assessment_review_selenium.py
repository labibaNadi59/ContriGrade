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
class InstructorAssessmentReviewSeleniumTests(StaticLiveServerTestCase):
    """
    Live browser Selenium UI tests for instructor assessment review.
    Selenium verifies that instructors can review assessment details,
    record viva observations, and adjust recommendations.
    Opens a visible Chrome browser window for live demonstration.
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
            email="inst_selenium_review@test.com",
            name="Prof. Alan Kay",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.coordinator = User.objects.create_user(
            email="coord_selenium_review@test.com",
            name="Coord Ada Lovelace",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.student_alice = User.objects.create_user(
            email="alice_selenium_review@test.com",
            name="Alice Smith",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.student_bob = User.objects.create_user(
            email="bob_selenium_review@test.com",
            name="Bob Jones",
            role=User.Role.STUDENT,
            password="password123"
        )

        # 2. Academic structure
        self.course = Course.objects.create(
            course_code="CSE499",
            course_name="Capstone Architecture Defense",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 1",
            instructor=self.instructor
        )
        self.section.students.add(self.student_alice, self.student_bob)

        self.project = Project.objects.create(
            section=self.section,
            title="Cloud Microservices Platform",
            deadline=timezone.now() + timedelta(days=14),
            weight_github=0,
            weight_deliverables=50,
            weight_peer=50
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Microservices Team"
        )
        TeamMember.objects.create(team=self.team, user=self.student_alice, role_in_team="Backend Lead")
        TeamMember.objects.create(team=self.team, user=self.student_bob, role_in_team="Frontend Lead")

        # 3. Evidence: Deliverables & Peer Evaluations
        deliv = NonCodingDeliverable.objects.create(
            team=self.team,
            submitted_by=self.student_alice,
            title="API Architecture Specification",
            link="https://docs.alpha.io/api"
        )
        DeliverableContribution.objects.create(
            deliverable=deliv,
            student=self.student_alice,
            contribution_area="gRPC & REST Endpoints",
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
            general_feedback="Solid backend architecture."
        )
        PeerEvaluationScore.objects.create(evaluation=pe, criterion=crit, score=5)

        # Target workspace URL computed dynamically via reverse
        path = reverse('student_evidence_detail', kwargs={
            'team_id': self.team.pk,
            'student_id': self.student_alice.user_id
        })
        self.target_url = f"{self.live_server_url}{path}"

    def _login_as_instructor(self):
        """Helper to log in as instructor via the visible browser."""
        self.driver.delete_all_cookies()
        self.driver.get(f"{self.live_server_url}/accounts/login/")
        user_field = self.wait.until(EC.presence_of_element_located((By.NAME, "username")))
        pass_field = self.driver.find_element(By.NAME, "password")
        submit_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")

        user_field.clear()
        user_field.send_keys("inst_selenium_review@test.com")
        pass_field.clear()
        pass_field.send_keys("password123")
        submit_btn.click()

        self.wait.until(EC.url_changes(f"{self.live_server_url}/accounts/login/"))
        time.sleep(0.5)

    # -------------------------------------------------------------------------
    # TEST 1: Review Assessment Details in UI
    # -------------------------------------------------------------------------
    def test_01_ui_review_assessment_details(self):
        """Selenium verifies instructor can view student evidence, formula points, and recommended score."""
        self._login_as_instructor()
        self.driver.get(self.target_url)

        # 1. Verify student identity and project title are displayed
        heading = self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(text(), 'Consolidated Assessment & Viva Review')]")))
        self.assertTrue(heading.is_displayed())
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Alice Smith", body_text)
        self.assertIn("Microservices Team", body_text)

        # 2. Verify evidence breakdown: Deliverables & Peer Reviews
        self.assertIn("API Architecture Specification", body_text)
        self.assertIn("Technical Contribution", body_text)

        # 3. Verify System Recommended Score (100.0%)
        self.assertIn("100.0%", body_text)
        self.assertTrue("recommended score" in body_text.lower())
        time.sleep(1)

    # -------------------------------------------------------------------------
    # TEST 2: Record Viva Observations (Draft Mode)
    # -------------------------------------------------------------------------
    def test_02_ui_record_viva_observations_draft(self):
        """Selenium verifies instructor can record viva defense observations and save as draft."""
        self._login_as_instructor()
        self.driver.get(self.target_url)

        # 1. Locate textarea and type viva observations
        viva_textarea = self.wait.until(EC.presence_of_element_located((By.ID, "viva_observations")))
        viva_notes = "Student demonstrated exceptional understanding of gRPC streaming and distributed tracing during live viva."
        viva_textarea.clear()
        viva_textarea.send_keys(viva_notes)
        time.sleep(0.8)

        # 2. Click Save Draft
        save_draft_btn = self.driver.find_element(By.XPATH, "//button[@name='action' and @value='save_assessment']")
        self.driver.execute_script("arguments[0].scrollIntoView(true);", save_draft_btn)
        time.sleep(0.3)
        save_draft_btn.click()

        # 3. Verify page reloads with success message and retains viva observations
        self.wait.until(EC.presence_of_element_located((By.ID, "viva_observations")))
        updated_textarea = self.driver.find_element(By.ID, "viva_observations")
        self.assertEqual(updated_textarea.get_attribute("value").strip(), viva_notes)

        # Verify DB persistence
        fa = FinalAssessment.objects.get(project=self.project, student=self.student_alice)
        self.assertEqual(fa.viva_observations, viva_notes)
        self.assertFalse(fa.is_approved)
        time.sleep(1)

    # -------------------------------------------------------------------------
    # TEST 3: Adjust Recommended Score with Valid Reason
    # -------------------------------------------------------------------------
    def test_03_ui_adjust_recommended_score_with_reason(self):
        """Selenium verifies instructor can adjust final score and enter an adjustment reason."""
        self._login_as_instructor()
        self.driver.get(self.target_url)

        # 1. Fill adjusted score and adjustment reason
        score_input = self.wait.until(EC.presence_of_element_located((By.ID, "adjusted_score")))
        score_input.clear()
        score_input.send_keys("95.0")

        reason_input = self.driver.find_element(By.ID, "adjustment_reason")
        reason_input.clear()
        reason_input.send_keys("Demonstrated complete mastery of distributed microservices.")
        time.sleep(0.8)

        # 2. Save assessment
        save_btn = self.driver.find_element(By.XPATH, "//button[@name='action' and @value='save_assessment']")
        self.driver.execute_script("arguments[0].scrollIntoView(true);", save_btn)
        time.sleep(0.3)
        save_btn.click()

        # 3. Verify UI renders adjusted final score and reason
        self.wait.until(EC.presence_of_element_located((By.ID, "adjusted_score")))
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("95.0%", body_text)
        self.assertTrue("adjusted final" in body_text.lower())

        # Verify database
        fa = FinalAssessment.objects.get(project=self.project, student=self.student_alice)
        self.assertEqual(fa.adjusted_score, 95.0)
        self.assertEqual(fa.adjustment_reason, "Demonstrated complete mastery of distributed microservices.")
        time.sleep(1)

    # -------------------------------------------------------------------------
    # TEST 4: Validate Score Adjustment Boundaries in UI
    # -------------------------------------------------------------------------
    def test_04_ui_validate_score_adjustment_boundaries(self):
        """Selenium verifies UI enforces boundary validation preventing scores outside 0-100."""
        self._login_as_instructor()
        self.driver.get(self.target_url)

        score_input = self.wait.until(EC.presence_of_element_located((By.ID, "adjusted_score")))
        # Verify HTML5 attributes
        self.assertEqual(score_input.get_attribute("min"), "0")
        self.assertEqual(score_input.get_attribute("max"), "100")

        # Attempt submitting invalid value > 100 via Javascript to test backend defense
        self.driver.execute_script("arguments[0].value = '140.0';", score_input)
        time.sleep(0.5)

        save_btn = self.driver.find_element(By.XPATH, "//button[@name='action' and @value='save_assessment']")
        self.driver.execute_script("arguments[0].scrollIntoView(true);", save_btn)
        time.sleep(0.3)
        save_btn.click()

        # Verify either HTML5 invalidation blocks submission or backend displays error message
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        if "Adjusted score must be between 0 and 100." in body_text:
            self.assertIn("Adjusted score must be between 0 and 100.", body_text)
        else:
            # HTML5 validation prevented submission: verify DB does not store 140.0
            self.assertFalse(FinalAssessment.objects.filter(student=self.student_alice, adjusted_score=140.0).exists())
        time.sleep(1)

    # -------------------------------------------------------------------------
    # TEST 5: Save and Approve Final Assessment in UI
    # -------------------------------------------------------------------------
    def test_05_ui_save_and_approve_final_assessment(self):
        """Selenium verifies instructor can officially approve the final score and unlock approval."""
        self._login_as_instructor()
        self.driver.get(self.target_url)

        # 1. Fill viva observations and adjusted score
        viva_textarea = self.wait.until(EC.presence_of_element_located((By.ID, "viva_observations")))
        viva_textarea.clear()
        viva_textarea.send_keys("Approved following successful oral defense.")

        score_input = self.driver.find_element(By.ID, "adjusted_score")
        score_input.clear()
        score_input.send_keys("96.0")

        reason_input = self.driver.find_element(By.ID, "adjustment_reason")
        reason_input.clear()
        reason_input.send_keys("Excellent defense.")
        time.sleep(0.8)

        # 2. Click Save & Approve
        approve_btn = self.driver.find_element(By.XPATH, "//button[@name='action' and @value='save_and_approve']")
        self.driver.execute_script("arguments[0].scrollIntoView(true);", approve_btn)
        time.sleep(0.3)
        approve_btn.click()

        # 3. Verify approved state in UI (unapprove button becomes available)
        unapprove_btn = self.wait.until(EC.presence_of_element_located((By.XPATH, "//button[@name='action' and @value='unapprove_score']")))
        self.assertTrue(unapprove_btn.is_displayed())

        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Prof. Alan Kay", body_text)
        self.assertIn("Unlock Approval", body_text)

        # Verify DB approval
        fa = FinalAssessment.objects.get(project=self.project, student=self.student_alice)
        self.assertTrue(fa.is_approved)
        self.assertEqual(fa.approved_by, self.instructor)
        time.sleep(1)

    # -------------------------------------------------------------------------
    # TEST 6: Reset Adjusted Recommendation to Recommended Baseline
    # -------------------------------------------------------------------------
    def test_06_ui_reset_score_to_recommended_baseline(self):
        """Selenium verifies clicking Revert to Recommended resets adjusted score while keeping viva notes."""
        # Pre-create adjusted assessment
        FinalAssessment.objects.create(
            project=self.project,
            team=self.team,
            student=self.student_alice,
            recommended_score=90.0,
            adjusted_score=98.0,
            adjustment_reason="Preliminary adjustment",
            viva_observations="Retained viva defense observations regarding system fault-tolerance.",
            is_approved=False,
            updated_by=self.instructor
        )

        self._login_as_instructor()
        self.driver.get(self.target_url)

        # 1. Verify Revert to Recommended button is visible
        revert_btn = self.wait.until(EC.presence_of_element_located((By.XPATH, "//button[@name='action' and @value='reset_score']")))
        self.assertTrue(revert_btn.is_displayed())
        time.sleep(0.8)

        # 2. Click Revert to Recommended
        self.driver.execute_script("arguments[0].scrollIntoView(true);", revert_btn)
        time.sleep(0.3)
        revert_btn.click()
        time.sleep(1)

        # 3. Verify adjusted score is cleared and recommended score is restored
        score_input = self.wait.until(EC.presence_of_element_located((By.ID, "adjusted_score")))
        self.assertEqual(score_input.get_attribute("value"), "")

        # Verify viva observations are preserved in UI
        viva_val = self.driver.find_element(By.ID, "viva_observations").get_attribute("value")
        self.assertIn("Retained viva defense observations regarding system fault-tolerance.", viva_val)

        # Verify DB
        fa = FinalAssessment.objects.get(project=self.project, student=self.student_alice)
        self.assertIsNone(fa.adjusted_score)
        self.assertEqual(fa.viva_observations, "Retained viva defense observations regarding system fault-tolerance.")
        time.sleep(1)

