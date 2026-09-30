
import uuid

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


def test_admin_creates_user_and_verify_information():

    # ==========================================
    # 1. Chrome Browser Setup
    # ==========================================

    options = Options()
    options.add_argument("--start-maximized")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)

    try:

        # ==========================================
        # 2. Test User Information
        # ==========================================

        random_str = uuid.uuid4().hex[:6]

        email = f"selenium_{random_str}@gmail.com"
        name = "Selenium Test User"
        password = "123"

        print("\n================================")
        print("TC-01: Admin Creates User")
        print("================================")
        print("Email:", email)

        # ==========================================
        # 3. Admin Login
        # ==========================================

        driver.get(
            "http://127.0.0.1:8000/accounts/login/"
        )

        username = wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "username")
            )
        )

        username.send_keys("sara@gmail.com")

        driver.find_element(
            By.NAME, "password"
        ).send_keys("123")

        driver.find_element(
            By.CSS_SELECTOR,
            "button[type='submit']"
        ).click()

        wait.until(
            EC.url_contains(
                "/accounts/system/dashboard/"
            )
        )

        print("Admin login successful")

        # ==========================================
        # 4. Open Create User Page
        # ==========================================

        driver.get(
            "http://127.0.0.1:8000/accounts/management/users/create/"
        )

        wait.until(
            EC.url_contains(
                "/accounts/management/users/create/"
            )
        )

        print("Create User page opened")

        # ==========================================
        # 5. Fill User Information
        # ==========================================

        wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "email")
            )
        ).send_keys(email)

        driver.find_element(
            By.NAME, "name"
        ).send_keys(name)

        Select(
            driver.find_element(By.NAME, "role")
        ).select_by_visible_text("Student")

        driver.find_element(
            By.NAME, "password"
        ).send_keys(password)

        # ==========================================
        # 6. Make User Active
        # ==========================================

        active = driver.find_element(
            By.NAME, "is_active"
        )

        if not active.is_selected():
            active.click()

        # ==========================================
        # 7. Save User
        # ==========================================

        save_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[@type='submit' and normalize-space()='Save User']"
                )
            )
        )

        save_button.click()

        print("Save User button clicked")

        # ==========================================
        # 8. Verify User Management Page
        # ==========================================

        wait.until(
            EC.url_contains(
                "/accounts/management/users/"
            )
        )

        print("User Management page opened")

        print("\n================================")
        print("TC-01 PASSED")
        print("================================")
        print("User successfully created.")
        print("Name:", name)
        print("Email:", email)
        print("Role: Student")
        print("================================")

        # ==================================================
        # TC-02
        # Verify Newly Created User Information
        # ==================================================

        print("\n================================")
        print("TC-02: Verify Newly Created User")
        print("================================")

        # Get complete User Management page text
        page_text = driver.find_element(
            By.TAG_NAME,
            "body"
        ).text

        # ------------------------------------------
        # Verify Name
        # ------------------------------------------

        assert name in page_text, (
            f"Created user's name '{name}' was not found."
        )

        print("Name verification: PASSED")

        # ------------------------------------------
        # Verify Email
        # ------------------------------------------

        assert email in page_text, (
            f"Created user's email '{email}' was not found."
        )

        print("Email verification: PASSED")

        # ------------------------------------------
        # Verify Role
        # ------------------------------------------

        assert "Student" in page_text, (
            "Created user's role 'Student' was not found."
        )

        print("Role verification: PASSED")

        # ==========================================
        # TC-02 Result
        # ==========================================

        print("\n================================")
        print("TC-02 PASSED")
        print("================================")
        print("Created user's information is")
        print("correctly displayed in User Management.")
        print("Name:", name)
        print("Email:", email)
        print("Role: Student")
        print("================================")

    finally:

        driver.quit()

