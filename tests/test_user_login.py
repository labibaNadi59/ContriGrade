
import uuid

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


def test_created_user_can_login():

    options = Options()
    options.add_argument("--start-maximized")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)

    # New user information
    random_str = uuid.uuid4().hex[:6]

    email = f"selenium_login_{random_str}@gmail.com"
    name = "Selenium Login User"
    password = "123"

    print("\n================================")
    print("TC-03: Created User Can Login")
    print("================================")
    print("Email:", email)

    # ==========================================
    # STEP 1: Admin Login
    # ==========================================

    driver.get(
        "http://127.0.0.1:8000/accounts/login/"
    )

    wait.until(
        EC.visibility_of_element_located(
            (By.NAME, "username")
        )
    ).send_keys("sara@gmail.com")

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
    # STEP 2: Create Student User
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

    active = driver.find_element(
        By.NAME, "is_active"
    )

    if not active.is_selected():
        active.click()

    save_button = wait.until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//button[@type='submit' and normalize-space()='Save User']"
            )
        )
    )

    save_button.click()

    wait.until(
        EC.url_contains(
            "/accounts/management/users/"
        )
    )

    print("New user created successfully")

    # ==========================================
    # STEP 3: Logout Admin
    # ==========================================

    driver.get(
        "http://127.0.0.1:8000/accounts/logout/"
    )

    print("Admin logout request completed")

    # ==========================================
    # STEP 4: Open Login Page
    # ==========================================

    driver.get(
        "http://127.0.0.1:8000/accounts/login/"
    )

    wait.until(
        EC.visibility_of_element_located(
            (By.NAME, "username")
        )
    )

    print("Login page opened")

    # ==========================================
    # STEP 5: Login as Created Student
    # ==========================================

    driver.find_element(
        By.NAME, "username"
    ).send_keys(email)

    driver.find_element(
        By.NAME, "password"
    ).send_keys(password)

    driver.find_element(
        By.CSS_SELECTOR,
        "button[type='submit']"
    ).click()

    # ==========================================
    # STEP 6: Verify Student Dashboard
    # ==========================================

    wait.until(
        EC.url_contains(
            "/student/dashboard/"
        )
    )

    print("Created user login successful")
    print("Student dashboard opened")

    # ==========================================
    # TC-03 PASSED
    # ==========================================

    print("\n================================")
    print("TC-03 PASSED")
    print("================================")
    print("Newly created user can login successfully.")
    print("Email:", email)
    print("================================")

    driver.quit()

