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
from academic.models import Course, CourseSection, Project, CourseAssessmentPolicy, EvaluationCriterion


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ConfigurationPersistenceSeleniumTests(StaticLiveServerTestCase):
    """
    Selenium test for configuration persistence.
    Acceptance criteria: Valid assessment weights are saved and remain correct
    after reloading the project.
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
            email="coord_sel_pers@test.com",
            name="Coord Persist",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_sel_pers@test.com",
            name="Prof. Persist",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE404",
            course_name="Database Internals",
            coordinator=self.coordinator
        )
        self.policy = CourseAssessmentPolicy.objects.create(
            course=self.course,
            weight_github=50,
            weight_deliverables=25,
            weight_peer=25
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section 01",
            instructor=self.instructor
        )
        self.project = Project.objects.create(
            section=self.section,
            title="B-Tree Engine",
            deadline=timezone.now() + timedelta(days=20),
            weight_github=50,
            weight_deliverables=25,
            weight_peer=25
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

    def test_01_saved_weights_persist_after_browser_reload(self):
        """Selenium verifies assessment weights display correctly and persist across page reload."""
        self._login("inst_sel_pers@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_url}")

        w_gh = self.wait.until(EC.presence_of_element_located((By.NAME, "weight_github")))
        w_del = self.driver.find_element(By.NAME, "weight_deliverables")
        w_pr = self.driver.find_element(By.NAME, "weight_peer")

        self.assertEqual(w_gh.get_attribute("value"), "50")
        self.assertEqual(w_del.get_attribute("value"), "25")
        self.assertEqual(w_pr.get_attribute("value"), "25")

        # Reload page
        self.driver.refresh()
        time.sleep(0.5)

        w_gh_reloaded = self.wait.until(EC.presence_of_element_located((By.NAME, "weight_github")))
        self.assertEqual(w_gh_reloaded.get_attribute("value"), "50")

    def test_02_newly_saved_weights_persist_on_project_page(self):
        """Selenium verifies instructor-updated weights persist after saving and reloading."""
        self._login("inst_sel_pers@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_url}")

        self.driver.execute_script("""
            var container = document.getElementById('locked-weights-container');
            if (container) {
                container.classList.remove('pointer-events-none', 'opacity-75');
            }
            document.getElementsByName('weight_github')[0].value = '45';
            document.getElementsByName('weight_deliverables')[0].value = '35';
            document.getElementsByName('weight_peer')[0].value = '20';
        """)

        save_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Save Project Changes')]")
        self.driver.execute_script("arguments[0].scrollIntoView(true);", save_btn)
        time.sleep(0.3)
        save_btn.click()
        time.sleep(1)

        # Re-fetch edit page
        self.driver.get(f"{self.live_server_url}{self.edit_url}")
        w_gh = self.wait.until(EC.presence_of_element_located((By.NAME, "weight_github")))
        self.assertEqual(w_gh.get_attribute("value"), "45")

    def test_03_saved_criteria_persist_across_reloads(self):
        """Selenium verifies added evaluation criterion persists and remains visible on reload."""
        self._login("inst_sel_pers@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_url}#peer-criteria")

        name_in = self.wait.until(EC.presence_of_element_located((By.NAME, "criterion_name")))
        max_in = self.driver.find_element(By.NAME, "criterion_max_score")
        name_in.send_keys("System Modularity")
        max_in.clear()
        max_in.send_keys("10")

        add_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Add Criterion')]")
        self.driver.execute_script("arguments[0].scrollIntoView(true);", add_btn)
        time.sleep(0.3)
        add_btn.click()
        time.sleep(1)

        # Reload
        self.driver.get(f"{self.live_server_url}{self.edit_url}#peer-criteria")
        body_text = self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body"))).text
        self.assertIn("System Modularity", body_text)
        self.assertIn("10", body_text)

    def test_04_updated_criterion_persists_after_reload(self):
        """Selenium verifies criterion updates persist after reload."""
        crit = EvaluationCriterion.objects.create(
            project=self.project,
            name="Basic Quality",
            max_score=5
        )
        self._login("inst_sel_pers@test.com", "password123")
        self.driver.get(f"{self.live_server_url}{self.edit_url}#peer-criteria")

        # Open edit criterion form
        self.driver.execute_script(f"toggleEditCriterion('{crit.pk}');")
        time.sleep(0.5)

        form_elem = self.wait.until(EC.presence_of_element_located((By.ID, f"edit-criterion-form-{crit.pk}")))
        name_input = form_elem.find_element(By.NAME, "criterion_name")
        max_input = form_elem.find_element(By.NAME, "criterion_max_score")

        name_input.clear()
        name_input.send_keys("Comprehensive Quality Review")
        max_input.clear()
        max_input.send_keys("8")

        update_btn = form_elem.find_element(By.XPATH, ".//button[contains(., 'Update Criterion')]")
        update_btn.click()
        time.sleep(1)

        # Reload and verify
        self.driver.get(f"{self.live_server_url}{self.edit_url}#peer-criteria")
        body_text = self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body"))).text
        self.assertIn("Comprehensive Quality Review", body_text)
        self.assertIn("8", body_text)

    def test_05_coordinator_policy_persists_across_sessions(self):
        """Selenium verifies coordinator-saved policy weights persist across login sessions."""
        self._login("coord_sel_pers@test.com", "password123")
        self.driver.get(f"{self.live_server_url}/academic/coordinator/courses/")

        edit_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@onclick, 'toggleEdit')]")))
        edit_btn.click()
        time.sleep(0.5)

        form_elem = self.wait.until(EC.presence_of_element_located((By.ID, f"edit-policy-{self.course.course_id}")))
        w_gh = form_elem.find_element(By.NAME, "weight_github")
        w_deliv = form_elem.find_element(By.NAME, "weight_deliverables")
        w_peer = form_elem.find_element(By.NAME, "weight_peer")

        w_gh.clear()
        w_gh.send_keys("45")
        w_deliv.clear()
        w_deliv.send_keys("35")
        w_peer.clear()
        w_peer.send_keys("20")

        save_btn = form_elem.find_element(By.CLASS_NAME, "save-btn")
        self.driver.execute_script("arguments[0].removeAttribute('disabled');", save_btn)
        save_btn.click()
        time.sleep(1)

        # Re-login in a fresh session
        self._login("coord_sel_pers@test.com", "password123")
        self.driver.get(f"{self.live_server_url}/academic/coordinator/courses/")

        body_text = self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body"))).text
        self.assertIn("45%", body_text)
        self.assertIn("35%", body_text)
        self.assertIn("20%", body_text)

    def test_06_complete_configuration_consistency_across_views(self):
        """Selenium verifies project configuration remains consistent across multiple navigations."""
        EvaluationCriterion.objects.create(project=self.project, name="Benchmark Rubric", max_score=10)
        self._login("inst_sel_pers@test.com", "password123")

        # 1. Check edit page
        self.driver.get(f"{self.live_server_url}{self.edit_url}")
        self.assertEqual(
            self.wait.until(EC.presence_of_element_located((By.NAME, "weight_github"))).get_attribute("value"),
            "50"
        )

        # 2. Navigate to dashboard
        self.driver.get(f"{self.live_server_url}/academic/dashboard/")
        self.wait.until(EC.presence_of_element_located((By.XPATH, f"//h4[contains(., '{self.project.title}')]")))

        # 3. Return to edit page
        self.driver.get(f"{self.live_server_url}{self.edit_url}#peer-criteria")
        body_text = self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body"))).text
        self.assertIn("Benchmark Rubric", body_text)
