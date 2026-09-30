from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager


LOGIN_URL = "http://127.0.0.1:8000/accounts/login/"
TEAM_URL = "http://127.0.0.1:8000/academic/teams/"


def login(driver):
    driver.get(LOGIN_URL)

    driver.find_element(
        By.NAME, "username"
    ).send_keys("sara@gmail.com")

    driver.find_element(
        By.NAME, "password"
    ).send_keys("123")

    driver.find_element(
        By.XPATH, "//button[@type='submit']"
    ).click()


def test_team_create_and_assign_successfully():
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    try:
        print("\n===== TC-01: Teams create and assign students successfully =====")

        login(driver)
        print("Login successful.")

        driver.get(TEAM_URL)

        print("Current URL:", driver.current_url)
        print("Page title:", driver.title)
        print("Project field count:", len(driver.find_elements(By.NAME, "project")))

        print("Page text:")
        print(driver.find_element(By.TAG_NAME, "body").text)

        project = Select(
            driver.find_element(By.NAME, "project")

        )
        project.select_by_index(1)

        driver.find_element(
            By.NAME, "team_name"
        ).send_keys("Selenium Successful Team")

        members = Select(
            driver.find_element(By.NAME, "members")
        )
        members.select_by_index(1)

        print("Project selected.")
        print("Student selected.")

        driver.find_element(
            By.XPATH,
            "//button[contains(normalize-space(), 'Create Team & Assign')]"
        ).click()

        assert "Selenium Successful Team" in driver.page_source

        print("Team created successfully.")
        print("TC-01 PASSED")

    finally:
        driver.quit()

# TC-2 (duplicate)
def test_duplicate_student_assignment_error():
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    try:
        print("\n===== TC-02: Duplicate student team assignment =====")

        login(driver)
        print("Login successful.")

        driver.get(TEAM_URL)

        project = Select(
            driver.find_element(By.NAME, "project")
        )
        project.select_by_index(1)

        driver.find_element(
            By.NAME, "team_name"
        ).send_keys("Selenium Duplicate Team 1")

        members = Select(
            driver.find_element(By.NAME, "members")
        )
        members.select_by_index(1)

        driver.find_element(
            By.XPATH,
            "//button[contains(normalize-space(), 'Create Team & Assign')]"
        ).click()

        print("First team created.")

        driver.get(TEAM_URL)

        project = Select(
            driver.find_element(By.NAME, "project")
        )
        project.select_by_index(1)

        driver.find_element(
            By.NAME, "team_name"
        ).send_keys("Selenium Duplicate Team 2")

        members = Select(
            driver.find_element(By.NAME, "members")
        )
        members.select_by_index(1)

        driver.find_element(
            By.XPATH,
            "//button[contains(normalize-space(), 'Create Team & Assign')]"
        ).click()

        page_text = driver.find_element(
            By.TAG_NAME, "body"
        ).text.lower()

        print("Message after duplicate assignment:")
        print(page_text)

        assert (
            "error" in page_text
            or "already" in page_text
            or "assigned" in page_text
        )

        print("Duplicate assignment error detected.")
        print("TC-02 PASSED")

    finally:
        driver.quit()