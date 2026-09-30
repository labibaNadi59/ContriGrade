from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def login_as_student(driver):

    driver.get("http://127.0.0.1:8000/accounts/login/")

    driver.find_element(
        By.NAME, "username"
    ).send_keys("sara@gmail.com")

    driver.find_element(
        By.NAME, "password"
    ).send_keys("123")

    driver.find_element(
        By.CSS_SELECTOR,
        "button[type='submit']"
    ).click()


def test_student_can_access_student_dashboard():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    try:
        # Login as Student
        login_as_student(driver)

        # Open Student Dashboard
        driver.get(
            "http://127.0.0.1:8000/academic/student/dashboard/"
        )

        # Student should be allowed
        assert "/academic/student/dashboard/" in driver.current_url

    finally:
        driver.quit()


def test_student_restricted_view_access_denied():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    try:
        # Login as Student
        login_as_student(driver)

        # Try to access restricted Coordinator Dashboard
        driver.get(
            "http://127.0.0.1:8000/academic/coordinator/dashboard/"
        )

        print("Current URL:", driver.current_url)
        print("Page title:", driver.title)

        # Student should NOT access Coordinator Dashboard
        assert "/academic/coordinator/dashboard/" not in driver.current_url

    finally:
        driver.quit()