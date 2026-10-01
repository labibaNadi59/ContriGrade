from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time


def test_deactivated_user_cannot_login():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    wait = WebDriverWait(driver, 10)

    try:

        # 1. Open Login Page
        driver.get("http://127.0.0.1:8000/accounts/login/")

        print("Login page opened")

        # 2. Enter deactivated user's email
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

        username.send_keys("zaima@gamil.com")
        password.send_keys("123")

        password.submit()

        time.sleep(2)

        print("Login attempt completed")
        print("Current URL:", driver.current_url)

        # 3. User should remain on login page
        assert "/accounts/login/" in driver.current_url

        print("SUCCESS: Deactivated user cannot login!")

    finally:
        driver.quit()