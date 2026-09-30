from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time

def test_deactivated_user_cannot_access_restricted_page():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    wait = WebDriverWait(driver, 10)

    try:

        # 1. Open Login Page
        driver.get("http://127.0.0.1:8000/accounts/login/")

        print("Login page opened")

        # 2. Enter deactivated user's email and password
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

        username.send_keys("zaima@gmail.com")
        password.send_keys("123")

        password.submit()

        time.sleep(2)

        print("Deactivated user login attempt completed")
        print("Current URL:", driver.current_url)

        # 3. Try to access restricted User Management page
        driver.get(
            "http://127.0.0.1:8000/accounts/management/users/"
        )

        time.sleep(2)

        print("Restricted page access attempted")
        print("Current URL:", driver.current_url)

        # 4. User should be redirected to login page
        assert "/accounts/login/" in driver.current_url

        print(
            "SUCCESS: Deactivated user cannot access restricted system functions!"
        )

    finally:
        driver.quit()