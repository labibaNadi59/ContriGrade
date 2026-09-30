
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

import time


def test_admin_updates_user():

    # ==========================================
    # 1. Start Chrome
    # ==========================================

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    wait = WebDriverWait(driver, 10)

    try:

        # ==========================================
        # 2. Open Login Page
        # ==========================================

        driver.get(
            "http://127.0.0.1:8000/accounts/login/"
        )

        print("Login page opened")


        # ==========================================
        # 3. Admin Login
        # ==========================================

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


        # ==========================================
        # 4. Open User Management
        # ==========================================

        driver.get(
            "http://127.0.0.1:8000/accounts/management/users/"
        )

        time.sleep(2)

        print("User management page opened")


        # ==========================================
        # 5. Find Update/Edit link
        # ==========================================

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


        # ==========================================
        # 6. Find Name field
        # ==========================================

        name_field = wait.until(
            EC.presence_of_element_located(
                (By.NAME, "name")
            )
        )


        # ==========================================
        # 7. Update Name
        # ==========================================

        name_field.clear()

        name_field.send_keys(
            "Helaly"
        )

        print("New name entered")


        # ==========================================
        # 8. Submit Update Form
        # ==========================================

        name_field.submit()

        time.sleep(2)

        print("Update submitted")
        print("Current URL:", driver.current_url)


        # ==========================================
        # 9. Verify successful redirect
        # ==========================================

        assert "/accounts/management/users/" in driver.current_url

        print(
            "SUCCESS: User account updated successfully!"
        )


    finally:

        # ==========================================
        # 10. Close browser
        # ==========================================

        driver.quit()

