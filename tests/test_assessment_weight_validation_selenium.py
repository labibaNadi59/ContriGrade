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
from academic.models import Course, CourseSection, Project, CourseAssessmentPolicy


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AssessmentWeightValidationSeleniumTests(StaticLiveServerTestCase):
    """
    Selenium test for assessment weight validation.
    Acceptance criteria: System rejects invalid weights and accepts valid
    weights that meet the defined total.
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
            email="coord_sel_val@test.com",
            name="Coord Weight Val",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_sel_val@test.com",
            name="Prof. Weight Val",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE403",
            course_name="Formal Methods",
            coordinator=self.coordinator
        )
        self.policy = CourseAssessmentPolicy.objects.create(
            course=self.course,
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 01",
            instructor=self.instructor
        )
        self.project = Project.objects.create(
            section=self.section,
            title="Formal Verifier",
            deadline=timezone.now() + timedelta(days=20),
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        self.edit_url = reverse('edit_project', kwargs={'project_id': self.project.pk})

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

    def test_01_coordinator_policy_ui_rejects_subtotal_under_100(self):
        """Selenium verifies coordinator policy save button is disabled when total is under 100%."""
        self._login("coord_sel_val@test.com", "password123")
        self.driver.get(f"{self.live_server_url}/academic/coordinator/courses/")

        edit_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@onclick, 'toggleEdit')]")))
        edit_btn.click()
        time.sleep(0.5)

        form_elem = self.wait.until(EC.presence_of_element_located((By.ID, f"edit-policy-{self.course.course_id}")))
        w_gh = form_elem.find_element(By.NAME, "weight_github")
        w_deliv = form_elem.find_element(By.NAME, "weight_deliverables")
        w_peer = form_elem.find_element(By.NAME, "weight_peer")

        w_gh.clear()
        w_gh.send_keys("30")
        w_deliv.clear()
        w_deliv.send_keys("30")
        w_peer.clear()
        w_peer.send_keys("30")
        # Trigger input event via JS
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", w_peer)
        time.sleep(0.5)

        save_btn = form_elem.find_element(By.CLASS_NAME, "save-btn")
        self.assertTrue(save_btn.get_attribute("disabled") is not None)

    def test_02_coordinator_policy_ui_rejects_subtotal_over_100(self):
        """Selenium verifies coordinator policy save button is disabled when total is over 100%."""
        self._login("coord_sel_val@test.com", "password123")
        self.driver.get(f"{self.live_server_url}/academic/coordinator/courses/")

        edit_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@onclick, 'toggleEdit')]")))
        edit_btn.click()
        time.sleep(0.5)

        form_elem = self.wait.until(EC.presence_of_element_located((By.ID, f"edit-policy-{self.course.course_id}")))
        w_gh = form_elem.find_element(By.NAME, "weight_github")
        w_deliv = form_elem.find_element(By.NAME, "weight_deliverables")
        w_peer = form_elem.find_element(By.NAME, "weight_peer")

        w_gh.clear()
        w_gh.send_keys("50")
        w_deliv.clear()
        w_deliv.send_keys("40")
        w_peer.clear()
        w_peer.send_keys("30")
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", w_peer)
        time.sleep(0.5)

        save_btn = form_elem.find_element(By.CLASS_NAME, "save-btn")
        self.assertTrue(save_btn.get_attribute("disabled") is not None)

    def test_03_coordinator_policy_ui_accepts_exact_100(self):
        """Selenium verifies coordinator policy save button is enabled when total is exactly 100%."""
        self._login("coord_sel_val@test.com", "password123")
        self.driver.get(f"{self.live_server_url}/academic/coordinator/courses/")

        edit_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@onclick, 'toggleEdit')]")))
        edit_btn.click()
        time.sleep(0.5)

        form_elem = self.wait.until(EC.presence_of_element_located((By.ID, f"edit-policy-{self.course.course_id}")))
        w_gh = form_elem.find_element(By.NAME, "weight_github")
        w_deliv = form_elem.find_element(By.NAME, "weight_deliverables")
        w_peer = form_elem.find_element(By.NAME, "weight_peer")

        w_gh.clear()
        w_gh.send_keys("50")
        w_deliv.clear()
        w_deliv.send_keys("25")
        w_peer.clear()
        w_peer.send_keys("25")
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", w_peer)
        time.sleep(0.5)

        save_btn = form_elem.find_element(By.CLASS_NAME, "save-btn")
        self.assertIsNone(save_btn.get_attribute("disabled"))

    def test_04_policy_request_modal_rejects_invalid_weights(self):
        """Selenium verifies policy request modal submit button remains disabled for invalid totals."""
        self._login("inst_sel_val@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_url}")

        req_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Request Custom Policy')]")))
        req_btn.click()
        time.sleep(0.5)

        modal = self.wait.until(EC.visibility_of_element_located((By.ID, "policy-request-panel")))
        w_gh = modal.find_element(By.NAME, "proposed_github")
        w_del = modal.find_element(By.NAME, "proposed_deliverables")
        w_pr = modal.find_element(By.NAME, "proposed_peer")

        w_gh.clear()
        w_gh.send_keys("40")
        w_del.clear()
        w_del.send_keys("30")
        w_pr.clear()
        w_pr.send_keys("20")  # total = 90%
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", w_pr)
        time.sleep(0.5)

        submit_btn = modal.find_element(By.ID, "submit-req-btn")
        self.assertTrue(submit_btn.get_attribute("disabled") is not None)

    def test_05_policy_request_modal_enables_submit_at_100(self):
        """Selenium verifies policy request modal submit button becomes enabled when total is 100%."""
        self._login("inst_sel_val@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_url}")

        req_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Request Custom Policy')]")))
        req_btn.click()
        time.sleep(0.5)

        modal = self.wait.until(EC.visibility_of_element_located((By.ID, "policy-request-panel")))
        w_gh = modal.find_element(By.NAME, "proposed_github")
        w_del = modal.find_element(By.NAME, "proposed_deliverables")
        w_pr = modal.find_element(By.NAME, "proposed_peer")

        w_gh.clear()
        w_gh.send_keys("60")
        w_del.clear()
        w_del.send_keys("20")
        w_pr.clear()
        w_pr.send_keys("20")  # total = 100%
        self.driver.execute_script("arguments[0].dispatchEvent(new Event('input'));", w_pr)
        time.sleep(0.5)

        submit_btn = modal.find_element(By.ID, "submit-req-btn")
        self.assertIsNone(submit_btn.get_attribute("disabled"))

    def test_06_server_validation_rejects_invalid_project_weights(self):
        """Selenium verifies server validation rejects non-100% weights and displays validation error."""
        self._login("inst_sel_val@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_url}")

        # Unlock weight fields in DOM and submit invalid total
        self.driver.execute_script("""
            var container = document.getElementById('locked-weights-container');
            if (container) {
                container.classList.remove('pointer-events-none', 'opacity-75');
            }
            document.getElementsByName('weight_github')[0].value = '50';
            document.getElementsByName('weight_deliverables')[0].value = '40';
            document.getElementsByName('weight_peer')[0].value = '30';
        """)

        save_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Save Project Changes')]")
        self.driver.execute_script("arguments[0].scrollIntoView(true);", save_btn)
        time.sleep(0.3)
        save_btn.click()
        time.sleep(1)

        body_text = self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body"))).text
        self.assertIn("Assessment weights must sum to exactly 100%", body_text)
