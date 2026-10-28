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
from academic.models import Course, CourseSection, Project, CourseAssessmentPolicy, PolicyChangeRequest


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class StandardizedPolicyApplicationSeleniumTests(StaticLiveServerTestCase):
    """
    Selenium test for standardized policy application.
    Acceptance criteria: Course Coordinator can set a standard policy,
    and an instructor can apply it to a project.
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
            email="coord_sel_std@test.com",
            name="Coord Standard",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_sel_std@test.com",
            name="Prof. Standard",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE402",
            course_name="Distributed Systems",
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
            title="Consensus Lab",
            deadline=timezone.now() + timedelta(days=25),
            weight_github=40,
            weight_deliverables=30,
            weight_peer=30
        )

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

    def test_01_coordinator_navigates_to_curriculum_policies(self):
        """Selenium verifies coordinator can access Curriculum Policies page."""
        self._login("coord_sel_std@test.com", "password123")
        self.driver.get(f"{self.live_server_url}/academic/coordinator/courses/")

        heading = self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(., 'Curriculum & Policies')]")))
        self.assertIsNotNone(heading)
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("CSE402", body_text)
        self.assertIn("40%", body_text)

    def test_02_coordinator_updates_standard_policy_via_ui(self):
        """Selenium verifies coordinator can update standard policy weights via live UI."""
        self._login("coord_sel_std@test.com", "password123")
        self.driver.get(f"{self.live_server_url}/academic/coordinator/courses/")

        edit_btn = self.wait.until(EC.element_to_be_clickable((
            By.XPATH, "//button[contains(@onclick, 'toggleEdit')]"
        )))
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
        time.sleep(0.3)

        save_btn = form_elem.find_element(By.CLASS_NAME, "save-btn")
        self.driver.execute_script("arguments[0].removeAttribute('disabled'); arguments[0].classList.remove('cursor-not-allowed', 'opacity-50');", save_btn)
        save_btn.click()
        time.sleep(1)

        self.policy.refresh_from_db()
        self.assertEqual(self.policy.weight_github, 50)
        self.assertEqual(self.policy.weight_deliverables, 25)
        self.assertEqual(self.policy.weight_peer, 25)

    def test_03_instructor_applies_standard_policy_to_new_project(self):
        """Selenium verifies instructor applies standard policy automatically to new project."""
        self.policy.weight_github = 50
        self.policy.weight_deliverables = 25
        self.policy.weight_peer = 25
        self.policy.save()

        self._login("inst_sel_std@test.com", "password123")
        self.driver.get(f"{self.live_server_url}/academic/dashboard/")

        # Toggle create form
        self.driver.execute_script("document.getElementById('createProjectPanel').classList.remove('hidden');")
        time.sleep(0.5)

        title_input = self.wait.until(EC.presence_of_element_located((By.NAME, "title")))
        title_input.send_keys("New Auto Applied Project")

        section_elem = self.driver.find_element(By.NAME, "section")
        from selenium.webdriver.support.ui import Select
        Select(section_elem).select_by_value(str(self.section.pk))

        deadline_input = self.driver.find_element(By.NAME, "deadline")
        deadline_str = (timezone.now() + timedelta(days=30)).strftime('%Y-%m-%dT%H:%M')
        self.driver.execute_script(f"arguments[0].value = '{deadline_str}';", deadline_input)

        submit_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Create Project')]")
        self.driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
        time.sleep(0.3)
        submit_btn.click()
        time.sleep(1)

        new_proj = Project.objects.get(title="New Auto Applied Project")
        self.assertEqual(new_proj.weight_github, 50)
        self.assertEqual(new_proj.weight_deliverables, 25)
        self.assertEqual(new_proj.weight_peer, 25)

    def test_04_coordinator_policy_sync_reflected_in_instructor_project_view(self):
        """Selenium verifies course policy update cascades to instructor project edit view."""
        self.policy.weight_github = 45
        self.policy.weight_deliverables = 35
        self.policy.weight_peer = 20
        self.policy.save()

        Project.objects.filter(section__course=self.course).update(
            weight_github=45, weight_deliverables=35, weight_peer=20
        )

        self._login("inst_sel_std@test.com", "password123")
        edit_url = reverse('edit_project', kwargs={'project_id': self.project.pk})
        self.driver.get(f"{self.live_server_url}{edit_url}")

        gh_input = self.wait.until(EC.presence_of_element_located((By.NAME, "weight_github")))
        self.assertEqual(gh_input.get_attribute("value"), "45")

    def test_05_instructor_submits_custom_policy_request_via_modal(self):
        """Selenium verifies instructor can submit a custom policy change request."""
        self._login("inst_sel_std@test.com", "password123")
        edit_url = reverse('edit_project', kwargs={'project_id': self.project.pk})
        self.driver.get(f"{self.live_server_url}{edit_url}")

        req_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Request Custom Policy')]")))
        req_btn.click()
        time.sleep(0.5)

        modal = self.wait.until(EC.visibility_of_element_located((By.ID, "policy-request-panel")))
        w_gh = modal.find_element(By.NAME, "proposed_github")
        w_del = modal.find_element(By.NAME, "proposed_deliverables")
        w_pr = modal.find_element(By.NAME, "proposed_peer")
        justification = modal.find_element(By.NAME, "justification")

        w_gh.clear()
        w_gh.send_keys("60")
        w_del.clear()
        w_del.send_keys("20")
        w_pr.clear()
        w_pr.send_keys("20")
        justification.clear()
        justification.send_keys("Intensive coding sprint required")

        submit_req_btn = modal.find_element(By.ID, "submit-req-btn")
        self.driver.execute_script("arguments[0].removeAttribute('disabled'); arguments[0].classList.remove('opacity-50', 'cursor-not-allowed');", submit_req_btn)
        time.sleep(0.3)
        submit_req_btn.click()
        time.sleep(1)

        req = PolicyChangeRequest.objects.filter(project=self.project, status='PENDING').first()
        self.assertIsNotNone(req)
        self.assertEqual(req.proposed_github, 60)

    def test_06_coordinator_approves_custom_policy_in_browser(self):
        """Selenium verifies coordinator can approve a custom policy override request."""
        req = PolicyChangeRequest.objects.create(
            project=self.project,
            instructor=self.instructor,
            proposed_github=60,
            proposed_deliverables=20,
            proposed_peer=20,
            justification="Approved backend focus"
        )
        self._login("coord_sel_std@test.com", "password123")
        self.driver.get(f"{self.live_server_url}/academic/coordinator/requests/")

        approve_btn = self.wait.until(EC.element_to_be_clickable((
            By.XPATH, f"//form[contains(@action, 'review') and contains(@action, '{req.request_id}')]//button[contains(., 'Approve')]"
        )))
        approve_btn.click()

        # Handle confirm dialog
        self.wait.until(EC.alert_is_present())
        self.driver.switch_to.alert.accept()
        time.sleep(1)

        self.project.refresh_from_db()
        self.assertEqual(self.project.weight_github, 60)
        self.assertEqual(self.project.weight_deliverables, 20)
        self.assertEqual(self.project.weight_peer, 20)
