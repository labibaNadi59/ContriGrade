from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time


def test_verify_updated_user_information():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    wait = WebDriverWait(driver, 10)

    try:

        # 1. Open Login Page
        driver.get(
            "http://127.0.0.1:8000/accounts/login/"
        )

        print("Login page opened")

        # 2. Admin Login
        username = wait.until(
            EC.presence_of_element_located(
                (By.NAME, "username")
            )
        )

        password = wait.until(
            EC.presence_of_element_located(
                (By.NAME, "password")
            )
        )

        username.send_keys("sara@gmail.com")
        password.send_keys("123")

        password.submit()

        time.sleep(2)

        print("Admin login completed")
        print("Current URL:", driver.current_url)

        # 3. Open User Management
        driver.get(
            "http://127.0.0.1:8000/accounts/management/users/"
        )

        time.sleep(2)

        print("User management page opened")

        # 4. Open Update Form
        update_link = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//a[contains(@href, '/update/')]"
                )
            )
        )

        update_link.click()

        print("User update page opened")

        # 5. Check updated name
        name_field = wait.until(
            EC.presence_of_element_located(
                (By.NAME, "name")
            )
        )

        updated_name = name_field.get_attribute("value")

        print("Current saved name:", updated_name)

        # 6. Verify the updated information
        assert updated_name == "Helaly"

        print(
            "SUCCESS: Updated user information is saved correctly!"
        )

    finally:
        driver.quit()