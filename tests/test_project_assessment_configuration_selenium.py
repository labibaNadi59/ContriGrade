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
from academic.models import Course, CourseSection, Project, EvaluationCriterion


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ProjectAssessmentConfigurationSeleniumTests(StaticLiveServerTestCase):
    """
    Selenium test for project assessment configuration.
    Acceptance criteria: Instructor can configure assessment criteria and weights,
    save them, and see the saved configuration after reloading.
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
            email="coord_sel_cfg@test.com",
            name="Coord Sel",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_sel_cfg@test.com",
            name="Prof. Sel Config",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE401",
            course_name="Software Architecture",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.project = Project.objects.create(
            section=self.section,
            title="Selenium Config Project",
            deadline=timezone.now() + timedelta(days=20),
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )
        self.edit_path = reverse('edit_project', kwargs={'project_id': self.project.pk})

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

    def test_01_navigate_to_configuration_page(self):
        """Selenium verifies instructor can navigate to project configuration interface."""
        self._login("inst_sel_cfg@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_path}")

        heading = self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(., 'Selenium Config Project')]")))
        self.assertIsNotNone(heading)
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Project Settings", body_text)
        self.assertIn("Peer Evaluation Criteria", body_text)

    def test_02_switch_to_criteria_tab(self):
        """Selenium verifies instructor can switch to the Peer Evaluation Criteria tab."""
        self._login("inst_sel_cfg@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_path}")

        criteria_tab_btn = self.wait.until(EC.element_to_be_clickable((By.ID, "tab-btn-criteria")))
        criteria_tab_btn.click()
        time.sleep(0.5)

        criteria_panel = self.wait.until(EC.visibility_of_element_located((By.ID, "tab-content-criteria")))
        self.assertTrue(criteria_panel.is_displayed())
        self.assertIn("Add New Criterion", criteria_panel.text)

    def test_03_add_new_criterion_via_browser(self):
        """Selenium verifies instructor can configure and add a new evaluation criterion."""
        self._login("inst_sel_cfg@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_path}#peer-criteria")

        name_input = self.wait.until(EC.presence_of_element_located((By.NAME, "criterion_name")))
        max_score_input = self.driver.find_element(By.NAME, "criterion_max_score")
        desc_input = self.driver.find_element(By.NAME, "criterion_description")
        add_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Add Criterion')]")

        name_input.clear()
        name_input.send_keys("Code Review Quality")
        max_score_input.clear()
        max_score_input.send_keys("10")
        desc_input.clear()
        desc_input.send_keys("Assessing PR feedback and discussion")

        self.driver.execute_script("arguments[0].scrollIntoView(true);", add_btn)
        time.sleep(0.3)
        add_btn.click()

        # Verify criterion is displayed
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Code Review Quality')]")))
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Code Review Quality", body_text)
        self.assertIn("10", body_text)

    def test_04_save_project_settings(self):
        """Selenium verifies instructor can update project details and save changes."""
        self._login("inst_sel_cfg@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_path}")

        desc_field = self.wait.until(EC.presence_of_element_located((By.NAME, "description")))
        desc_field.clear()
        desc_field.send_keys("Updated project description via Selenium UI")

        save_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Save Project Changes')]")
        self.driver.execute_script("arguments[0].scrollIntoView(true);", save_btn)
        time.sleep(0.3)
        save_btn.click()

        time.sleep(1)
        self.project.refresh_from_db()
        self.assertEqual(self.project.description, "Updated project description via Selenium UI")

    def test_05_delete_criterion_via_browser(self):
        """Selenium verifies instructor can remove an existing criterion."""
        crit = EvaluationCriterion.objects.create(
            project=self.project,
            name="Temporary Metric",
            max_score=5
        )
        self._login("inst_sel_cfg@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_path}#peer-criteria")

        delete_btn = self.wait.until(EC.element_to_be_clickable((
            By.XPATH, f"//button[@name='delete_criterion' and @value='{crit.pk}']"
        )))
        self.driver.execute_script("arguments[0].scrollIntoView(true);", delete_btn)
        time.sleep(0.3)
        delete_btn.click()

        # Handle JS confirm dialog
        self.wait.until(EC.alert_is_present())
        self.driver.switch_to.alert.accept()
        time.sleep(1)

        self.assertFalse(EvaluationCriterion.objects.filter(pk=crit.pk).exists())

    def test_06_saved_configuration_visible_after_reloading(self):
        """Selenium verifies saved criteria and configuration remain visible after browser reload."""
        EvaluationCriterion.objects.create(
            project=self.project,
            name="Architecture Integrity",
            max_score=10
        )
        self._login("inst_sel_cfg@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_path}#peer-criteria")

        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Architecture Integrity')]")))

        # Reload browser
        self.driver.refresh()
        time.sleep(0.5)

        # Switch to criteria tab if needed and verify
        self.driver.get(f"{self.live_server_url}{self.edit_path}#peer-criteria")
        body_text = self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body"))).text
        self.assertIn("Architecture Integrity", body_text)
        self.assertIn("10", body_text)
