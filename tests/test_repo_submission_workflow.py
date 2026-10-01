import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import requests
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()

from django.test.utils import setup_test_environment, teardown_test_environment
from django.test import Client
from django.contrib.messages import get_messages

from academic.models import Team, TeamMember, Project
from accounts.models import User
from academic.forms import TeamRepoForm
from academic.utils import validate_github_repo_url

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "http://127.0.0.1:8000"


def wait_for_text_in_element(driver, by, value, expected_text, timeout=25):
    """Wait until an element contains expected text to prevent stale element issues."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            elem = driver.find_element(by, value)
            if expected_text.lower() in elem.text.lower():
                return elem
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Text '{expected_text}' not found in {by}={value} within {timeout}s")


# =====================================================================
# 1. URL FORMAT & API VALIDATION ENGINE UNIT TESTS
# =====================================================================
class TestRepoValidationEngine(unittest.TestCase):
    """
    Tests the core validation utility: validate_github_repo_url()
    Checks format parsing, sanitization, and GitHub REST API integration.
    """

    def test_empty_and_none_url(self):
        res_empty = validate_github_repo_url("")
        self.assertFalse(res_empty["valid"])
        self.assertIn("No URL provided", res_empty["error"])

        res_none = validate_github_repo_url(None)
        self.assertFalse(res_none["valid"])
        self.assertIn("No URL provided", res_none["error"])

    def test_non_github_domains_rejected(self):
        bad_urls = [
            "https://gitlab.com/octocat/Hello-World",
            "https://bitbucket.org/octocat/Hello-World",
            "https://sourceforge.net/projects/hello-world",
            "https://example.com/octocat/Hello-World",
        ]
        for url in bad_urls:
            res = validate_github_repo_url(url)
            self.assertFalse(res["valid"], f"Expected {url} to be rejected")
            self.assertIn("Invalid format", res["error"])

    def test_incomplete_and_malformed_urls_rejected(self):
        bad_urls = [
            "https://github.com",
            "https://github.com/",
            "https://github.com/octocat",
            "https://github.com/octocat/",
            "octocat/Hello-World",
            "git@github.com:octocat/Hello-World.git",
            "ftp://github.com/octocat/Hello-World",
            "https://github.com/octocat/Hello-World/tree/main",
            "https://github.com/octocat/Hello-World/pulls",
        ]
        for url in bad_urls:
            res = validate_github_repo_url(url)
            self.assertFalse(res["valid"], f"Expected {url} to be rejected")
            self.assertIn("Invalid format", res["error"])

    @patch('requests.get')
    def test_valid_github_url_formats_and_sanitization(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        # Standard HTTPS
        res = validate_github_repo_url("https://github.com/octocat/Hello-World")
        self.assertTrue(res["valid"])
        self.assertEqual(res["clean_url"], "https://github.com/octocat/Hello-World")

        # Standard HTTP
        res = validate_github_repo_url("http://github.com/octocat/Hello-World")
        self.assertTrue(res["valid"])
        self.assertEqual(res["clean_url"], "https://github.com/octocat/Hello-World")

        # With www subdomain
        res = validate_github_repo_url("https://www.github.com/octocat/Hello-World")
        self.assertTrue(res["valid"])
        self.assertEqual(res["clean_url"], "https://github.com/octocat/Hello-World")

        # With trailing slash
        res = validate_github_repo_url("https://github.com/octocat/Hello-World/")
        self.assertTrue(res["valid"])
        self.assertEqual(res["clean_url"], "https://github.com/octocat/Hello-World")

        # With .git suffix (clone URL)
        res = validate_github_repo_url("https://github.com/octocat/Hello-World.git")
        self.assertTrue(res["valid"])
        self.assertEqual(res["clean_url"], "https://github.com/octocat/Hello-World")

        # With whitespace padding
        res = validate_github_repo_url("  https://github.com/octocat/Hello-World  ")
        self.assertTrue(res["valid"])
        self.assertEqual(res["clean_url"], "https://github.com/octocat/Hello-World")

    @patch('requests.get')
    def test_api_404_repo_not_found(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        res = validate_github_repo_url("https://github.com/octocat/NonExistentRepo")
        self.assertFalse(res["valid"])
        self.assertIn("not found", res["error"].lower())

    @patch('requests.get')
    def test_api_401_invalid_token(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        res = validate_github_repo_url("https://github.com/octocat/Hello-World")
        self.assertFalse(res["valid"])
        self.assertIn("invalid", res["error"].lower())

    @patch('requests.get')
    def test_api_network_exception_handling(self, mock_get):
        mock_get.side_effect = requests.RequestException("Connection timed out")

        res = validate_github_repo_url("https://github.com/octocat/Hello-World")
        self.assertFalse(res["valid"])
        self.assertIn("network error", res["error"].lower())


# =====================================================================
# 2. TEAM REPO FORM VALIDATION UNIT TESTS
# =====================================================================
class TestTeamRepoFormValidation(unittest.TestCase):
    """
    Tests Django TeamRepoForm validation logic, field errors, and clean_url generation.
    """

    def setUp(self):
        self.team = Team.objects.filter(pk=2).first()
        if not self.team:
            self.skipTest("Team 2 not in database")

    @patch('academic.forms.validate_github_repo_url')
    def test_form_valid_url(self, mock_validator):
        mock_validator.return_value = {
            "valid": True,
            "error": None,
            "clean_url": "https://github.com/octocat/Hello-World"
        }
        form = TeamRepoForm(data={'github_repo_url': 'https://github.com/octocat/Hello-World.git'}, instance=self.team)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['github_repo_url'], "https://github.com/octocat/Hello-World")

    @patch('academic.forms.validate_github_repo_url')
    def test_form_invalid_url_raises_error(self, mock_validator):
        mock_validator.return_value = {
            "valid": False,
            "error": "Invalid format. Use: https://github.com/owner/repo"
        }
        form = TeamRepoForm(data={'github_repo_url': 'https://gitlab.com/owner/repo'}, instance=self.team)
        self.assertFalse(form.is_valid())
        self.assertIn('github_repo_url', form.errors)
        self.assertIn("Invalid format", form.errors['github_repo_url'][0])

    @patch('academic.forms.validate_github_repo_url')
    def test_form_not_found_repo_raises_error(self, mock_validator):
        mock_validator.return_value = {
            "valid": False,
            "error": "Repository 'owner/fake' not found. Ensure it is public or the System API token has access to it."
        }
        form = TeamRepoForm(data={'github_repo_url': 'https://github.com/owner/fake'}, instance=self.team)
        self.assertFalse(form.is_valid())
        self.assertIn('github_repo_url', form.errors)
        self.assertIn("not found", form.errors['github_repo_url'][0])


# =====================================================================
# 3. VIEW & SECURITY WORKFLOW TESTS (DJANGO TEST CLIENT)
# =====================================================================
class TestRepoSubmissionViewWorkflow(unittest.TestCase):
    """
    Tests security access control, authentication, authorization, GET form rendering,
    and POST submissions with status codes, redirects, flash messages, and DB updates.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        setup_test_environment()

    @classmethod
    def tearDownClass(cls):
        teardown_test_environment()
        super().tearDownClass()

    def setUp(self):
        self.client = Client()
        self.student_in_team = User.objects.filter(email='labiba@gmail.com').first()
        self.student_other = User.objects.filter(email='sowrov@gmail.com').first()
        self.instructor = User.objects.filter(email='tanjina@gmail.com').first()
        self.team = Team.objects.filter(pk=2).first()

        if not (self.student_in_team and self.student_other and self.team):
            self.skipTest("Required seed data (users/teams) not present in database")

        self.repo_url = f"/academic/student/team/{self.team.team_id}/repo/"

    def test_unauthenticated_user_redirected_to_login(self):
        resp = self.client.get(self.repo_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_non_student_role_access_blocked(self):
        if self.instructor:
            self.client.force_login(self.instructor)
            resp = self.client.get(self.repo_url)
            # Instructor is blocked by @student_required decorator -> raises PermissionDenied (HTTP 403)
            self.assertEqual(resp.status_code, 403)

    def test_unauthorized_student_blocked_by_security_check(self):
        """
        Student who is NOT a member of Team 2 cannot view or submit repo for Team 2.
        Must receive security block flash message and redirect to student dashboard.
        """
        self.client.force_login(self.student_other)
        resp = self.client.get(self.repo_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any("/academic/student/" in redir[0] for redir in resp.redirect_chain))

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Security block: You can only link repositories for your own team" in m for m in messages))

    def test_authorized_student_get_form_success(self):
        """
        Student member of Team 2 can load the repository link page.
        """
        self.client.force_login(self.student_in_team)
        resp = self.client.get(self.repo_url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Link GitHub Repository", content)
        self.assertIn(self.team.team_name, content)
        self.assertIn("github_repo_url", content)

    @patch('academic.forms.validate_github_repo_url')
    def test_authorized_student_post_invalid_format(self, mock_validator):
        """
        Posting invalid format fails form validation, does NOT save to DB, re-renders page with error.
        """
        original_repo = self.team.github_repo_url
        mock_validator.return_value = {
            "valid": False,
            "error": "Invalid format. Use: https://github.com/owner/repo"
        }

        self.client.force_login(self.student_in_team)
        resp = self.client.post(self.repo_url, {'github_repo_url': 'https://gitlab.com/fake/repo'})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("Invalid format. Use: https://github.com/owner/repo", content)

        # Verify DB was NOT modified
        self.team.refresh_from_db()
        self.assertEqual(self.team.github_repo_url, original_repo)

    @patch('academic.forms.validate_github_repo_url')
    def test_authorized_student_post_repo_not_found(self, mock_validator):
        """
        Posting non-existent repo fails API existence check, does NOT save to DB.
        """
        original_repo = self.team.github_repo_url
        mock_validator.return_value = {
            "valid": False,
            "error": "Repository 'owner/ghost' not found. Ensure it is public or the System API token has access to it."
        }

        self.client.force_login(self.student_in_team)
        resp = self.client.post(self.repo_url, {'github_repo_url': 'https://github.com/owner/ghost'})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn("not found", content)

        # Verify DB was NOT modified
        self.team.refresh_from_db()
        self.assertEqual(self.team.github_repo_url, original_repo)

    @patch('academic.forms.validate_github_repo_url')
    def test_authorized_student_post_valid_repo_success(self, mock_validator):
        """
        Posting valid repo passes validation, updates database, and redirects with success message.
        """
        new_repo = "https://github.com/labibaNadi59/ContriGrade"
        mock_validator.return_value = {
            "valid": True,
            "error": None,
            "clean_url": new_repo
        }

        self.client.force_login(self.student_in_team)
        resp = self.client.post(self.repo_url, {'github_repo_url': f"{new_repo}.git"}, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any("/academic/student/" in redir[0] for redir in resp.redirect_chain))

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("Successfully linked GitHub repository" in m for m in messages))

        # Verify DB update
        self.team.refresh_from_db()
        self.assertEqual(self.team.github_repo_url, new_repo)


# =====================================================================
# 4. LIVE SELENIUM E2E BROWSER TESTS
# =====================================================================
class TestRepoSubmissionSeleniumE2E(unittest.TestCase):
    """
    End-to-End browser tests covering the live submission & validation workflow:
    - Format validation in UI
    - Non-existent repo error in UI
    - Valid repository submission with redirect & dashboard display
    - Security block for unauthorized student
    """

    def setUp(self):
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--log-level=3")

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(self.driver, 25)

    def tearDown(self):
        if self.driver:
            self.driver.quit()

    def _login(self, email, password):
        self.driver.get(f"{BASE_URL}/accounts/login/")
        user_field = self.wait.until(EC.presence_of_element_located((By.NAME, "username")))
        pass_field = self.driver.find_element(By.NAME, "password")
        submit_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")

        user_field.clear()
        user_field.send_keys(email)
        pass_field.clear()
        pass_field.send_keys(password)
        submit_btn.click()

        self.wait.until(lambda d: "/accounts/login/" not in d.current_url)

    def test_e2e_invalid_format_rejected(self):
        """Test submitting non-GitHub domain in UI displays format validation error."""
        print("\n[E2E] Testing UI rejection of invalid URL format...")
        self._login("labiba@gmail.com", "123")

        repo_link_url = f"{BASE_URL}/academic/student/team/2/repo/"
        self.driver.get(repo_link_url)

        header = self.wait.until(EC.visibility_of_element_located((By.TAG_NAME, "h2"))).text
        self.assertIn("Link GitHub Repository", header)

        url_input = self.wait.until(EC.presence_of_element_located((By.NAME, "github_repo_url")))
        url_input.clear()
        url_input.send_keys("https://gitlab.com/owner/repo")

        submit_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Validate & Save')]")
        submit_btn.click()

        error_elem = wait_for_text_in_element(self.driver, By.XPATH, "//p[contains(@class, 'text-red-500')]", "Invalid format", timeout=20)
        self.assertIn("Invalid format", error_elem.text)
        print(f"  -> UI Format Validation Error Verified: '{error_elem.text}'")
        print("  -> [PASSED] E2E Invalid Format Rejection")

    def test_e2e_nonexistent_repo_rejected(self):
        """Test submitting non-existent repo in UI displays 404 API error."""
        print("\n[E2E] Testing UI rejection of non-existent GitHub repository...")
        self._login("labiba@gmail.com", "123")

        repo_link_url = f"{BASE_URL}/academic/student/team/2/repo/"
        self.driver.get(repo_link_url)

        url_input = self.wait.until(EC.presence_of_element_located((By.NAME, "github_repo_url")))
        url_input.clear()
        url_input.send_keys("https://github.com/nonexistentowner998877/nonexistentrepo998877")

        submit_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Validate & Save')]")
        submit_btn.click()

        error_elem = wait_for_text_in_element(self.driver, By.XPATH, "//p[contains(@class, 'text-red-500')]", "not found", timeout=25)
        self.assertIn("not found", error_elem.text.lower())
        print(f"  -> UI Existence Validation Error Verified: '{error_elem.text}'")
        print("  -> [PASSED] E2E Non-existent Repo Rejection")

    def test_e2e_valid_repo_submission_and_dashboard_display(self):
        """Test submitting valid repo updates DB, redirects to student dashboard, and renders link."""
        print("\n[E2E] Testing successful repository submission and dashboard update...")
        self._login("labiba@gmail.com", "123")

        repo_link_url = f"{BASE_URL}/academic/student/team/2/repo/"
        self.driver.get(repo_link_url)

        valid_repo = "https://github.com/labibaNadi59/ContriGrade"
        url_input = self.wait.until(EC.presence_of_element_located((By.NAME, "github_repo_url")))
        url_input.clear()
        url_input.send_keys(valid_repo)

        submit_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Validate & Save')]")
        submit_btn.click()

        # Verify redirection to student dashboard with success message
        self.wait.until(lambda d: "/student" in d.current_url and "/repo/" not in d.current_url)
        body_text = wait_for_text_in_element(self.driver, By.TAG_NAME, "body", "Successfully linked GitHub repository", timeout=20).text
        self.assertIn("Successfully linked GitHub repository", body_text)
        print("  -> Success flash message displayed on Student Dashboard.")

        # Verify Dashboard displays repo link
        repo_links = self.driver.find_elements(By.XPATH, f"//a[contains(@href, '{valid_repo}')]")
        self.assertGreater(len(repo_links), 0, "Student dashboard should display the linked repo link")
        print("  -> Linked repository verified visible on Student Dashboard.")
        print("  -> [PASSED] E2E Valid Repo Submission & Dashboard Display")

    def test_e2e_unauthorized_student_access_security_block(self):
        """Test student from another team cannot access or submit repo for Team 2."""
        print("\n[E2E] Testing Security Block for Unauthorized Student...")
        self._login("sowrov@gmail.com", "123")

        unauthorized_url = f"{BASE_URL}/academic/student/team/2/repo/"
        self.driver.get(unauthorized_url)

        self.wait.until(lambda d: "/repo/" not in d.current_url and "/student" in d.current_url)
        body_text = wait_for_text_in_element(self.driver, By.TAG_NAME, "body", "Security block", timeout=20).text

        self.assertIn("Security block: You can only link repositories for your own team", body_text)
        print("  -> Security block verified: Unauthorized student was blocked and redirected.")
        print("  -> [PASSED] E2E Security Block Test")


if __name__ == '__main__':
    print("=" * 70)
    print(" ContriGrade Repository Submission & Validation Workflow Test Suite")
    print("=" * 70)
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestRepoValidationEngine))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestTeamRepoFormValidation))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestRepoSubmissionViewWorkflow))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestRepoSubmissionSeleniumE2E))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(not result.wasSuccessful())

