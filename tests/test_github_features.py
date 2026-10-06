import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
import unittest
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "http://127.0.0.1:8000"
LOGIN_URL = f"{BASE_URL}/accounts/login/"


def get_driver(headless=True):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    # Do NOT mix implicit wait with explicit waits
    return driver


def wait_for_element(driver, by, value, timeout=30):
    """Robust element waiter that avoids stale reference / implicit wait clashes."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            elem = driver.find_element(by, value)
            if elem.is_displayed():
                return elem
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"Element {by}={value} not found or not visible within {timeout}s")


def wait_for_text_in_element(driver, by, value, expected_text, timeout=30):
    """Waits until an element contains expected text."""
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


def perform_login(driver, email, password):
    driver.get(LOGIN_URL)
    wait = WebDriverWait(driver, 15)

    # Wait for login form
    username_field = wait.until(EC.presence_of_element_located((By.NAME, "username")))
    password_field = driver.find_element(By.NAME, "password")
    submit_btn = driver.find_element(By.XPATH, "//button[@type='submit']")

    username_field.clear()
    username_field.send_keys(email)
    password_field.clear()
    password_field.send_keys(password)
    submit_btn.click()

    # Wait until redirected away from login page
    wait.until(lambda d: "/accounts/login/" not in d.current_url)
    time.sleep(1)


class TestGitHubFeatures(unittest.TestCase):

    def setUp(self):
        self.driver = get_driver(headless=True)
        self.wait = WebDriverWait(self.driver, 30)

    def tearDown(self):
        if self.driver:
            self.driver.quit()

    def test_tc_gh_01_admin_github_api_connection(self):
        """TC-GH-01: Admin tests GitHub API connection in System API Settings."""
        print("\n[RUNNING] TC-GH-01: Admin GitHub API Connection Test")
        perform_login(self.driver, "nadi@gmail.com", "123")

        # Navigate to System API Settings (accurate route)
        api_settings_url = f"{BASE_URL}/accounts/management/api-settings/"
        self.driver.get(api_settings_url)

        # Verify page header
        header = wait_for_element(self.driver, By.TAG_NAME, "h2").text
        self.assertIn("System API Settings", header)

        # Check Token Configured badge
        page_source = self.driver.page_source
        self.assertIn("GitHub API Integration", page_source)
        self.assertIn("Token Configured in .env", page_source)

        # Find and click "Test Connection" button
        test_button = wait_for_element(self.driver, By.XPATH, "//button[@name='test_connection']")
        test_button.click()

        # Wait for status response container
        status_box = wait_for_element(
            self.driver, By.XPATH, "//div[contains(@class, 'rounded-lg border') and contains(@class, 'text-sm')]"
        )
        status_text = status_box.text
        print("  -> API Status Result:", status_text.replace("\n", " | "))

        self.assertIn("Connected successfully as", status_text)
        self.assertIn("API Calls Remaining:", status_text)
        print("  -> [PASSED] TC-GH-01")

    def test_tc_gh_02_student_profile_github_username_validation(self):
        """TC-GH-02: Student Profile settings validates GitHub username against GitHub API."""
        print("\n[RUNNING] TC-GH-02: Student Profile GitHub Username Validation")
        perform_login(self.driver, "labiba@gmail.com", "123")

        profile_url = f"{BASE_URL}/accounts/profile/"
        self.driver.get(profile_url)

        # Verify profile form and github_username field
        gh_input = wait_for_element(self.driver, By.NAME, "github_username")
        self.assertIsNotNone(gh_input)

        # Test Case A: Enter invalid non-existent username
        fake_username = "nonexistent_gh_user_xyz_99881177665544"
        gh_input.clear()
        gh_input.send_keys(fake_username)

        submit_btn = wait_for_element(self.driver, By.XPATH, "//button[contains(., 'Save Profile')]")
        submit_btn.click()

        # Wait for validation error to appear
        error_elem = wait_for_text_in_element(self.driver, By.XPATH, "//p[contains(@class, 'text-red-500')]", "not found", timeout=25)
        print("  -> Validation Error Shown:", error_elem.text)
        self.assertIn(f"GitHub user '{fake_username}' not found", error_elem.text)

        # Test Case B: Enter valid username and save
        valid_username = "labibaNadi59"
        gh_input = wait_for_element(self.driver, By.NAME, "github_username")
        gh_input.clear()
        gh_input.send_keys(valid_username)

        submit_btn = wait_for_element(self.driver, By.XPATH, "//button[contains(., 'Save Profile')]")
        submit_btn.click()

        # Student is redirected to student dashboard on success
        self.wait.until(lambda d: "/student" in d.current_url)
        print("  -> Successful submission redirected to:", self.driver.current_url)
        self.assertIn("student", self.driver.current_url.lower())
        print("  -> [PASSED] TC-GH-02")

    def test_tc_gh_03_team_repo_validation_and_link(self):
        """TC-GH-03: Team GitHub repository linking validates URL format & GitHub repo existence."""
        print("\n[RUNNING] TC-GH-03: Team GitHub Repository URL Validation & Linking")
        perform_login(self.driver, "labiba@gmail.com", "123")

        repo_link_url = f"{BASE_URL}/academic/student/team/2/repo/"
        self.driver.get(repo_link_url)

        # Check page header
        header = wait_for_element(self.driver, By.TAG_NAME, "h2").text
        self.assertIn("Link GitHub Repository", header)

        # Sub-test 1: Submit non-existent repository URL
        url_input = wait_for_element(self.driver, By.NAME, "github_repo_url")
        url_input.clear()
        url_input.send_keys("https://github.com/nonexistentowner998877/nonexistentrepo998877")

        save_btn = wait_for_element(self.driver, By.XPATH, "//button[contains(., 'Validate & Save')]")
        save_btn.click()

        # Expect API existence error
        error_elem = wait_for_text_in_element(self.driver, By.XPATH, "//p[contains(@class, 'text-red-500')]", "not found", timeout=25)
        print("  -> Repo Not Found Error Shown:", error_elem.text)
        self.assertIn("not found", error_elem.text.lower())

        # Sub-test 2: Submit valid repository URL
        valid_repo = "https://github.com/labibaNadi59/ContriGrade"
        url_input = wait_for_element(self.driver, By.NAME, "github_repo_url")
        url_input.clear()
        url_input.send_keys(valid_repo)

        save_btn = wait_for_element(self.driver, By.XPATH, "//button[contains(., 'Validate & Save')]")
        save_btn.click()

        # Should redirect away from repo edit page to student dashboard with success message
        self.wait.until(lambda d: "/repo/" not in d.current_url and "/student" in d.current_url)
        dashboard_text = wait_for_text_in_element(self.driver, By.TAG_NAME, "body", "Successfully linked GitHub repository").text
        self.assertIn("Successfully linked GitHub repository", dashboard_text)
        print("  -> Successfully verified and linked repository:", valid_repo)
        print("  -> [PASSED] TC-GH-03")

    def test_tc_gh_04_student_team_progress_dashboard(self):
        """TC-GH-04: Student views team progress dashboard with GitHub commits & visual charts."""
        print("\n[RUNNING] TC-GH-04: Student Team Progress Analytics & UI Elements")
        perform_login(self.driver, "labiba@gmail.com", "123")

        progress_url = f"{BASE_URL}/academic/student/team/2/progress/"
        self.driver.get(progress_url)

        # Verify Page Header
        header = wait_for_element(self.driver, By.TAG_NAME, "h2").text
        self.assertIn("Team Progress: VoltShare", header)

        # Verify Action Buttons
        refresh_btn = wait_for_element(self.driver, By.XPATH, "//a[contains(., 'Refresh')]")
        repo_link = wait_for_element(self.driver, By.XPATH, "//a[contains(., 'View Repo')]")
        self.assertTrue(refresh_btn.is_displayed())
        self.assertIn("github.com/labibaNadi59/ContriGrade", repo_link.get_attribute("href"))

        # Verify Summary Stat Cards (case-insensitive for CSS transforms)
        body_text_upper = self.driver.find_element(By.TAG_NAME, "body").text.upper()
        self.assertIn("TOTAL TEAM COMMITS", body_text_upper)
        self.assertIn("ACTIVE CONTRIBUTORS", body_text_upper)
        self.assertIn("ACTIVE BRANCHES", body_text_upper)
        self.assertIn("LIVE DATA", body_text_upper)

        # Verify Chart.js Canvas Elements
        timeline_canvas = self.driver.find_element(By.ID, "timelineChart")
        split_canvas = self.driver.find_element(By.ID, "splitChart")
        self.assertTrue(timeline_canvas.is_displayed())
        self.assertTrue(split_canvas.is_displayed())

        # Verify Team Member rows with commits and percentage
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("My Team's Contributions", body_text)
        self.assertIn("labiba", body_text.lower())
        self.assertIn("commits", body_text.lower())

        print("  -> Progress cards, Chart.js canvases, and contributor rows verified.")
        print("  -> [PASSED] TC-GH-04")

    def test_tc_gh_05_instructor_team_analytics_and_integrity_flags(self):
        """TC-GH-05: Instructor views Team Analytics with Recent Commits feed & Integrity Flags."""
        print("\n[RUNNING] TC-GH-05: Instructor Team Analytics & Integrity Flags Engine")
        perform_login(self.driver, "tanjina@gmail.com", "123")

        analytics_url = f"{BASE_URL}/academic/instructor/team/2/analytics/"
        self.driver.get(analytics_url)

        # Header Check
        header = wait_for_element(self.driver, By.TAG_NAME, "h2").text
        self.assertIn("Team Analytics", header)

        # Verify 4 Stat Cards
        body_text_upper = self.driver.find_element(By.TAG_NAME, "body").text.upper()
        self.assertIn("TOTAL COMMITS", body_text_upper)
        self.assertIn("MAPPED STUDENTS", body_text_upper)
        self.assertIn("UNMAPPED COMMITS", body_text_upper)
        self.assertIn("ACTIVE BRANCHES", body_text_upper)

        # Verify Charts
        timeline_canvas = self.driver.find_element(By.ID, "timelineChart")
        split_canvas = self.driver.find_element(By.ID, "splitChart")
        self.assertTrue(timeline_canvas.is_displayed())
        self.assertTrue(split_canvas.is_displayed())

        # Verify Commits Feed
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertTrue(
            "project commits feed" in body_text.lower() or "recent commits feed" in body_text.lower(),
            "Commits feed header should be displayed on page"
        )

        # Check commit entry presence
        commit_elements = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'divide-y')]//p[contains(@class, 'font-mono')]")
        self.assertGreater(len(commit_elements), 0, "Recent Commits Feed should display commits")
        print(f"  -> Found {len(commit_elements)} commits displayed in Recent Commits Feed.")

        # Verify Student Contribution Breakdown & Integrity Flags
        self.assertIn("Student Contributions", body_text)
        print("  -> Instructor Analytics, Chart visualizers, and Commits Feed verified.")
        print("  -> [PASSED] TC-GH-05")

    def test_tc_gh_06_instructor_master_report_and_csv_export(self):
        """TC-GH-06: Instructor views Master Class Report with GitHub metrics and tests CSV export."""
        print("\n[RUNNING] TC-GH-06: Master Report & CSV Export")
        perform_login(self.driver, "tanjina@gmail.com", "123")

        report_url = f"{BASE_URL}/academic/instructor/project/2/report/"
        self.driver.get(report_url)

        # Header check
        header = wait_for_element(self.driver, By.TAG_NAME, "h2").text
        self.assertIn("Master Class Report", header)

        # Stats check (uppercase-safe)
        body_text_upper = self.driver.find_element(By.TAG_NAME, "body").text.upper()
        self.assertIn("TOTAL STUDENTS", body_text_upper)
        self.assertIn("TOTAL CLASS COMMITS", body_text_upper)
        self.assertIn("TEAMS CONNECTED", body_text_upper)

        # Check Table Headers (uppercase-safe)
        table_headers = [th.text.upper() for th in self.driver.find_elements(By.TAG_NAME, "th")]
        print("  -> Table Columns:", ", ".join(table_headers))
        self.assertTrue(any("STUDENT" in th for th in table_headers))
        self.assertTrue(any("COMMITS" in th for th in table_headers))
        self.assertTrue(any("LINES OF CODE" in th for th in table_headers))

        # Check CSV Export link
        csv_link = wait_for_element(self.driver, By.XPATH, "//a[contains(@href, 'export=csv')]")
        self.assertIsNotNone(csv_link)
        csv_href = csv_link.get_attribute("href")
        self.assertIn("export=csv", csv_href)

        # Direct test of CSV export endpoint using current cookies
        cookies = {c['name']: c['value'] for c in self.driver.get_cookies()}
        resp = requests.get(csv_href, cookies=cookies)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers.get("Content-Type", ""))
        self.assertIn("Student Name,GitHub Username,Team,Role,Commits,Lines Added,Lines Deleted,Integrity Flags", resp.text)
        print("  -> CSV Export verified successfully with HTTP 200 and standard CSV header row.")
        print("  -> [PASSED] TC-GH-06")


if __name__ == "__main__":
    print("=" * 70)
    print(" ContriGrade GitHub Integration Selenium Test Suite")
    print(" Target: http://127.0.0.1:8000")
    print("=" * 70)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestGitHubFeatures)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(not result.wasSuccessful())


