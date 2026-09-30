import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
from webdriver_manager.chrome import ChromeDriverManager

# =========================================================
# TC-01
# Student Dashboard Role & Responsibility form load
# =========================================================

def test_student_role_form_load():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    driver.maximize_window()

    wait = WebDriverWait(driver, 10)

    try:

        # 1. Open Login Page
        driver.get(
            "http://127.0.0.1:8000/accounts/login/"
        )

        # 2. Enter Username
        username = wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "username")
            )
        )
        username.send_keys("tia@gmail.com")

        # 3. Enter Password
        password = wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "password")
            )
        )
        password.send_keys("123")

        # 4. Click Login
        login_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "button[type='submit']"
                )
            )
        )
        login_button.click()

        # 5. Wait for Dashboard
        wait.until(
            EC.url_contains(
                "/academic/student/dashboard/"
            )
        )

        print("\nLogin successful.")

        # 6. Open Student Dashboard
        driver.get(
            "http://127.0.0.1:8000/academic/student/dashboard/"
        )

        wait.until(
            EC.visibility_of_element_located(
                (By.TAG_NAME, "body")
            )
        )

        print("\n==============================")
        print("TC-01: STUDENT ROLE FORM")
        print("==============================")

        print(
            "Dashboard URL:",
            driver.current_url
        )

        print(
            "Page Title:",
            driver.title
        )

        # 7. Find Define Role / Edit Role
        role_link = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(normalize-space(), 'Define Role') "
                    "or contains(normalize-space(), 'Edit Role')]"
                )
            )
        )

        assert role_link.is_displayed()

        print(
            "\nDefine Role / Edit Role link found."
        )

        print(
            "Role link URL:",
            role_link.get_attribute("href")
        )

        # 8. Click Role Link
        role_link.click()

        # 9. Wait for Role Page
        wait.until(
            EC.url_contains(
                "/academic/student/memberships/"
            )
        )

        print(
            "Role page URL:",
            driver.current_url
        )

        # 10. Check Heading
        heading = wait.until(
            EC.visibility_of_element_located(
                (
                    By.XPATH,
                    "//h2[contains(normalize-space(), "
                    "'Project Role & Responsibilities')]"
                )
            )
        )

        assert heading.is_displayed()

        print(
            "Project Role & Responsibilities heading found."
        )

        # 11. Check Form
        form = wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "form[method='post']"
                )
            )
        )

        assert form.is_displayed()

        print(
            "Role & Responsibility form found."
        )

        # 12. Check Role Dropdown
        role_dropdown = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_role_choice")
            )
        )

        assert role_dropdown.is_displayed()

        print(
            "Role dropdown found."
        )

        # 13. Check Responsibilities Field
        responsibilities = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_responsibilities")
            )
        )

        assert responsibilities.is_displayed()

        print(
            "Responsibilities field found."
        )

        # TC-01 PASS
        print("\n========================================")
        print("TC-01 PASSED")
        print(
            "Student Role & Responsibility form "
            "loaded successfully."
        )
        print("========================================")

    finally:

        driver.quit()


# =========================================================
# TC-02
# Student Role & Responsibility save
# =========================================================

def test_student_project_role_save():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    driver.maximize_window()

    wait = WebDriverWait(driver, 10)

    try:

        # 1. Open Login Page
        driver.get(
            "http://127.0.0.1:8000/accounts/login/"
        )

        # 2. Enter Username
        username = wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "username")
            )
        )
        username.send_keys("tia@gmail.com")

        # 3. Enter Password
        password = wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "password")
            )
        )
        password.send_keys("123")

        # 4. Click Login
        login_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "button[type='submit']"
                )
            )
        )
        login_button.click()

        # 5. Wait for Dashboard
        wait.until(
            EC.url_contains(
                "/academic/student/dashboard/"
            )
        )

        print("\n========================================")
        print("TC-02: SAVE ROLE & RESPONSIBILITY")
        print("========================================")

        print("Login successful.")

        # 6. Open Student Dashboard
        driver.get(
            "http://127.0.0.1:8000/academic/student/dashboard/"
        )

        wait.until(
            EC.visibility_of_element_located(
                (By.TAG_NAME, "body")
            )
        )

        print("Student Dashboard opened.")

        # 7. Find Define Role / Edit Role
        role_link = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(normalize-space(), 'Define Role') "
                    "or contains(normalize-space(), 'Edit Role')]"
                )
            )
        )

        print(
            "Define Role / Edit Role link found."
        )

        # 8. Click Role Link
        role_link.click()

        # 9. Wait for Role Page
        wait.until(
            EC.url_contains(
                "/academic/student/memberships/"
            )
        )

        print("Role page opened.")

        # 10. Check Role Dropdown
        role_dropdown = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_role_choice")
            )
        )

        assert role_dropdown.is_displayed()

        # 11. Select a Role
        select = Select(role_dropdown)

        selected_role = None

        for option in select.options:

            value = option.get_attribute("value")
            text = option.text.strip()

            if value and value != "Other":

                select.select_by_value(value)

                selected_role = text

                break

        assert selected_role is not None

        print(
            "Selected Role:",
            selected_role
        )

        # 12. Enter Responsibilities
        responsibilities = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_responsibilities")
            )
        )

        expected_responsibilities = (
            "Complete assigned project tasks, "
            "prepare required documentation, "
            "and contribute to project development."
        )

        responsibilities.clear()

        responsibilities.send_keys(
            expected_responsibilities
        )

        print(
            "Responsibilities entered."
        )

        # 13. Click Save Role Details
        save_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(normalize-space(), "
                    "'Save Role Details')]"
                )
            )
        )

        save_button.click()

        print(
            "Save Role Details button clicked."
        )

        # 14. Wait for Dashboard
        wait.until(
            EC.url_contains(
                "/academic/student/dashboard/"
            )
        )

        print(
            "Returned to Student Dashboard."
        )

        # 15. Get Dashboard Text
        dashboard_text = wait.until(
            EC.visibility_of_element_located(
                (By.TAG_NAME, "body")
            )
        ).text

        # 16. Verify Role Saved
        assert selected_role in dashboard_text

        print(
            "Saved role verified."
        )

        # 17. Verify Responsibilities Saved
        assert expected_responsibilities in dashboard_text

        print(
            "Saved responsibilities verified."
        )

        # TC-02 PASS
        print("\n========================================")
        print("TC-02 PASSED")
        print(
            "Student project role and responsibilities "
            "saved successfully."
        )
        print("========================================")

    finally:

        driver.quit()


# =========================================================
# TC-03
# Student Project Role & Responsibility Update
# =========================================================

def test_student_project_role_update():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    driver.maximize_window()

    wait = WebDriverWait(driver, 10)

    try:

        # 1. Open Login Page
        driver.get(
            "http://127.0.0.1:8000/accounts/login/"
        )

        # 2. Enter Username
        username = wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "username")
            )
        )
        username.send_keys("tia@gmail.com")

        # 3. Enter Password
        password = wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "password")
            )
        )
        password.send_keys("123")

        # 4. Click Login
        login_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "button[type='submit']"
                )
            )
        )
        login_button.click()

        # 5. Wait for Dashboard
        wait.until(
            EC.url_contains(
                "/academic/student/dashboard/"
            )
        )

        print("\n========================================")
        print("TC-03: UPDATE ROLE & RESPONSIBILITY")
        print("========================================")

        print("Login successful.")

        # 6. Open Student Dashboard
        driver.get(
            "http://127.0.0.1:8000/academic/student/dashboard/"
        )

        wait.until(
            EC.visibility_of_element_located(
                (By.TAG_NAME, "body")
            )
        )

        print("Student Dashboard opened.")

        # 7. Find Edit Role / Define Role
        role_link = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(normalize-space(), 'Edit Role') "
                    "or contains(normalize-space(), 'Define Role')]"
                )
            )
        )

        print(
            "Edit Role / Define Role link found."
        )

        # 8. Click Edit Role
        role_link.click()

        # 9. Wait for Role Page
        wait.until(
            EC.url_contains(
                "/academic/student/memberships/"
            )
        )

        print("Role page opened.")

        # 10. Find Role Dropdown
        role_dropdown = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_role_choice")
            )
        )

        assert role_dropdown.is_displayed()

        # 11. Select a DIFFERENT role
        select = Select(role_dropdown)

        updated_role = None

        for option in select.options:

            value = option.get_attribute("value")
            text = option.text.strip()

            if value and text not in [
                "",
                "Other",
                "Frontend Developer"
            ]:

                select.select_by_value(value)

                updated_role = text

                break

        assert updated_role is not None

        print(
            "Updated Role:",
            updated_role
        )

        # 12. Find Responsibilities field
        responsibilities = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_responsibilities")
            )
        )

        # 13. Enter UPDATED responsibilities
        updated_responsibilities = (
            "Develop and test assigned modules, "
            "fix project issues, update documentation, "
            "and coordinate with team members."
        )

        responsibilities.clear()

        responsibilities.send_keys(
            updated_responsibilities
        )

        print(
            "Updated responsibilities entered."
        )

        # 14. Click Save Role Details
        save_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(normalize-space(), "
                    "'Save Role Details')]"
                )
            )
        )

        save_button.click()

        print(
            "Save Role Details button clicked."
        )

        # 15. Wait for Dashboard
        wait.until(
            EC.url_contains(
                "/academic/student/dashboard/"
            )
        )

        print(
            "Returned to Student Dashboard."
        )

        # 16. Get Dashboard Text
        dashboard_text = wait.until(
            EC.visibility_of_element_located(
                (By.TAG_NAME, "body")
            )
        ).text

        # 17. Verify UPDATED role
        assert updated_role in dashboard_text

        print(
            "Updated role verified."
        )

        # 18. Verify UPDATED responsibilities
        assert updated_responsibilities in dashboard_text

        print(
            "Updated responsibilities verified."
        )

        # TC-03 PASS
        print("\n========================================")
        print("TC-03 PASSED")
        print(
            "Student project role and responsibilities "
            "updated successfully."
        )
        print("========================================")

    finally:

        driver.quit()

# Tc-4 (Empty /invalid data)

def test_student_project_role_validation():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    driver.maximize_window()

    wait = WebDriverWait(driver, 10)

    try:

        # 1. Open Login Page
        driver.get(
            "http://127.0.0.1:8000/accounts/login/"
        )

        # 2. Enter Username
        username = wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "username")
            )
        )

        username.send_keys("tia@gmail.com")

        # 3. Enter Password
        password = wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "password")
            )
        )

        password.send_keys("123")

        # 4. Click Login
        login_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "button[type='submit']"
                )
            )
        )

        login_button.click()

        # 5. Wait for Student Dashboard
        wait.until(
            EC.url_contains(
                "/academic/student/dashboard/"
            )
        )

        print("\n========================================")
        print("TC-04: EMPTY DATA VALIDATION")
        print("========================================")

        print("Login successful.")

        # 6. Open Student Dashboard
        driver.get(
            "http://127.0.0.1:8000/academic/student/dashboard/"
        )

        wait.until(
            EC.visibility_of_element_located(
                (By.TAG_NAME, "body")
            )
        )

        print("Student Dashboard opened.")

        # 7. Find Edit Role / Define Role
        role_link = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(normalize-space(), 'Edit Role') "
                    "or contains(normalize-space(), 'Define Role')]"
                )
            )
        )

        print("Edit Role / Define Role link found.")

        # 8. Click Role Link
        role_link.click()

        # 9. Wait for Role Page
        wait.until(
            EC.url_contains(
                "/academic/student/memberships/"
            )
        )

        print("Role page opened.")

        # 10. Find Role Dropdown
        role_dropdown = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_role_choice")
            )
        )

        print("Role dropdown found.")

        # 11. Find Responsibilities field
        responsibilities = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_responsibilities")
            )
        )

        print("Responsibilities field found.")

        # 12. Clear Responsibilities
        responsibilities.clear()

        print("Responsibilities field cleared.")

        # 13. Select empty option from Role dropdown
        select = Select(role_dropdown)

        try:
            select.select_by_value("")
            print("Empty role selected.")
        except Exception:
            print("Empty role option not available.")

        # 14. Find Save button
        save_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(normalize-space(), "
                    "'Save Role Details')]"
                )
            )
        )

        # 15. Click Save
        save_button.click()

        print("Save Role Details button clicked.")

        # Give browser time to process validation
        time.sleep(1)

        # 16. Check current URL
        current_url = driver.current_url

        print(
            "Current URL after Save:",
            current_url
        )

        # 17. Get current page text AFTER clicking Save
        body_text = driver.find_element(
            By.TAG_NAME,
            "body"
        ).text

        print("\nPage text after empty submit:")
        print("----------------------------------------")
        print(body_text)
        print("----------------------------------------")

        # 18. Check HTML5 validation message
        validation_found = False

        # Find elements again - DO NOT use old references
        try:

            new_role_dropdown = driver.find_element(
                By.ID,
                "id_role_choice"
            )

            role_validation_message = (
                new_role_dropdown.get_attribute(
                    "validationMessage"
                )
            )

            if role_validation_message:

                print(
                    "Role validation message:",
                    role_validation_message
                )

                validation_found = True

        except Exception:
            pass

        try:

            new_responsibilities = driver.find_element(
                By.ID,
                "id_responsibilities"
            )

            responsibility_validation_message = (
                new_responsibilities.get_attribute(
                    "validationMessage"
                )
            )

            if responsibility_validation_message:

                print(
                    "Responsibility validation message:",
                    responsibility_validation_message
                )

                validation_found = True

        except Exception:
            pass

        # 19. Check Django error messages
        error_keywords = [
            "required",
            "this field is required",
            "field is required",
            "please correct",
            "error",
            "invalid",
            "required field"
        ]

        for keyword in error_keywords:

            if keyword.lower() in body_text.lower():

                print(
                    "Validation/error text found:",
                    keyword
                )

                validation_found = True

                break

        # 20. Check whether form stayed on role page
        if "/academic/student/memberships/" in current_url:

            print(
                "Form remained on Role page."
            )

            validation_found = True

        # 21. Final verification
        assert validation_found, (
            "TC-04 FAILED: Empty data was accepted "
            "without validation/error."
        )

        print("\n========================================")
        print("TC-04 PASSED")
        print(
            "Empty/invalid data validation "
            "is working successfully."
        )
        print("========================================")

    finally:

        driver.quit()

# TC-05  (login log out save)

# =========================================================

# TC-05

# Saved Role & Responsibility remains after Logout/Login

# =========================================================
def test_role_persistence():
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    driver.maximize_window()
    wait = WebDriverWait(driver, 10)

    try:
        print("\n===== TC-05: DATA PERSISTENCE =====")

        driver.get("http://127.0.0.1:8000/accounts/login/")

        wait.until(
            EC.visibility_of_element_located((By.NAME, "username"))
        ).send_keys("tia@gmail.com")

        wait.until(
            EC.visibility_of_element_located((By.NAME, "password"))
        ).send_keys("123")

        wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[type='submit']")
            )
        ).click()

        wait.until(
            EC.url_contains("/academic/student/dashboard/")
        )

        print("Login successful.")

        driver.get(
            "http://127.0.0.1:8000/academic/student/dashboard/"
        )

        role_link = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(normalize-space(), 'Edit Role') "
                    "or contains(normalize-space(), 'Define Role')]"
                )
            )
        )

        role_link.click()

        wait.until(
            EC.url_contains("/academic/student/memberships/")
        )

        role_dropdown = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_role_choice")
            )
        )

        Select(role_dropdown).select_by_visible_text(
            "Frontend Developer"
        )

        responsibilities = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_responsibilities")
            )
        )

        expected_text = (
            "Design and develop the frontend interface "
            "of the project."
        )

        responsibilities.clear()
        responsibilities.send_keys(expected_text)

        wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(normalize-space(), "
                    "'Save Role Details')]"
                )
            )
        ).click()

        wait.until(
            EC.url_contains("/academic/student/dashboard/")
        )

        print("Data saved.")

        # Logout
        # Logout
        logout = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//*[contains(normalize-space(), 'Sign Out') "
                    "or contains(normalize-space(), 'Logout')]"
                )
            )
        )

        print("Logout button found.")

        driver.execute_script(
            "arguments[0].click();",
            logout
        )

        time.sleep(2)

        print("Logout clicked.")
        print("Current URL:", driver.current_url)

        # Check login page
        if "/accounts/login/" not in driver.current_url:
            driver.get(
                "http://127.0.0.1:8000/accounts/login/"
            )

        wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "username")
            )
        )

        print("Logout successful.")

        wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "username")
            )
        ).send_keys("tia@gmail.com")

        wait.until(
            EC.visibility_of_element_located(
                (By.NAME, "password")
            )
        ).send_keys("123")

        wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[type='submit']")
            )
        ).click()

        wait.until(
            EC.url_contains("/academic/student/dashboard/")
        )

        print("Login again successful.")

        driver.get(
            "http://127.0.0.1:8000/academic/student/dashboard/"
        )

        wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "//a[contains(normalize-space(), 'Edit Role') "
                    "or contains(normalize-space(), 'Define Role')]"
                )
            )
        ).click()

        wait.until(
            EC.url_contains("/academic/student/memberships/")
        )

        role_dropdown = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_role_choice")
            )
        )

        responsibilities = wait.until(
            EC.visibility_of_element_located(
                (By.ID, "id_responsibilities")
            )
        )

        saved_role = Select(
            role_dropdown
        ).first_selected_option.text.strip()

        saved_text = responsibilities.get_attribute("value")

        print("Saved Role:", saved_role)
        print("Saved Responsibilities:", saved_text)

        assert saved_role == "Frontend Developer"
        assert saved_text == expected_text

        print("TC-05 PASSED")

    finally:
        driver.quit()