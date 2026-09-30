from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


LOGIN_URL = "http://127.0.0.1:8000/accounts/login/"
STUDENT_DASHBOARD_URL = (
    "http://127.0.0.1:8000/academic/student/dashboard/"
)


def login_as_student(driver, username, password):

    driver.get(LOGIN_URL)

    driver.find_element(
        By.NAME, "username"
    ).send_keys(username)

    driver.find_element(
        By.NAME, "password"
    ).send_keys(password)

    driver.find_element(
        By.CSS_SELECTOR,
        "button[type='submit']"
    ).click()

    print("Login URL:", driver.current_url)


def test_student_dashboard_team_project_deadline():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    try:
        print("\n===== TC-01: Dashboard shows team, project, and deadlines =====")

        # Login as student
        login_as_student(
            driver,
            "tia@gmail.com",
            "123"
        )

        print("Login successful.")

        # Open Student Dashboard
        driver.get(STUDENT_DASHBOARD_URL)

        print("Current URL:", driver.current_url)
        print("Page title:", driver.title)

        page_text = driver.find_element(
            By.TAG_NAME, "body"
        ).text

        print("Dashboard content:")
        print(page_text)

        # Student Dashboard must load successfully
        assert "403 Forbidden" not in page_text, (
            "Student Dashboard returned 403 Forbidden."
        )

        assert "Student Dashboard" in driver.title, (
            "Student Dashboard page did not load."
        )

        # Check project
        assert "CSE 314" in page_text, (
            "Project name was not found on dashboard."
        )

        # Check deadline
        assert "Deadline:" in page_text, (
            "Deadline was not found on dashboard."
        )

        # Check team
        assert "My Team:" in page_text, (
            "Team information was not found on dashboard."
        )

        print("Team found.")
        print("Project found.")
        print("Deadline found.")
        print("TC-01 PASSED")

    finally:
        driver.quit()


def test_student_empty_team_state():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    try:
        print("\n===== TC-02: Empty state shows if unassigned =====")

        # Login as student
        login_as_student(
            driver,
            "onti@gmail.com",
            "123"
        )

        print("Login successful.")

        # Open Student Dashboard
        driver.get(STUDENT_DASHBOARD_URL)

        print("Current URL:", driver.current_url)
        print("Page title:", driver.title)

        page_text = driver.find_element(
            By.TAG_NAME, "body"
        ).text

        print("Dashboard content:")
        print(page_text)

        # Dashboard must load successfully
        assert "403 Forbidden" not in page_text, (
            "Student Dashboard returned 403 Forbidden."
        )

        # Student without a team should see empty state
        assert "No Team Assigned Yet" in page_text, (
            "Empty team message was not displayed."
        )

        print("Empty team state displayed.")
        print("TC-02 PASSED")

    finally:
        driver.quit()