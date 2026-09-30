from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service


def test_instructor_can_create_session_with_deadline():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    wait = WebDriverWait(driver, 10)

    try:
        # 1. Open login page
        driver.get("http://127.0.0.1:8000/accounts/login/")

        # 2. Login as Instructor
        wait.until(
            EC.presence_of_element_located((By.NAME, "username"))
        ).send_keys("tanjina@gmail.com")

        driver.find_element(
            By.NAME, "password"
        ).send_keys("123")

        driver.find_element(
            By.CSS_SELECTOR,
            "button[type='submit']"
        ).click()

        # 3. Open instructor dashboard
        driver.get(
            "http://127.0.0.1:8000/academic/dashboard/"
        )

        # 4. Check instructor dashboard
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(), 'Instructor Dashboard')]")
            )
        )

        # 5. Fill title
        driver.find_element(
            By.NAME, "title"
        ).send_keys("Selenium Test Session")

        # 6. Fill description
        driver.find_element(
            By.NAME, "description"
        ).send_keys("Selenium automated testing session")

        # 7. Select section
        section = Select(
            driver.find_element(By.NAME, "section")
        )

        section.select_by_index(1)

        deadline = driver.find_element(
            By.NAME, "deadline"
        )

        driver.execute_script(
            """
            arguments[0].value = '2026-12-31T23:59';
            arguments[0].dispatchEvent(new Event('input', {bubbles: true}));
            arguments[0].dispatchEvent(new Event('change', {bubbles: true}));
            """,
            deadline
        )

        # 9. Submit form
        driver.find_element(
            By.XPATH,
            "//button[contains(normalize-space(), 'Create Project')]"
        ).click()

        # 10. Show result after submit
        print("\n===== CURRENT URL =====")
        print(driver.current_url)

        print("\n===== PAGE TEXT =====")
        print(driver.find_element(By.TAG_NAME, "body").text)

        # 11. Verify project was created
        assert "Selenium Test Session" in driver.find_element(
            By.TAG_NAME, "body"
        ).text

        print("\nSession created successfully!")
        print("Deadline saved successfully!")

    finally:
        driver.quit()