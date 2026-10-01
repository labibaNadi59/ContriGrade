"""
Selenium E2E and Integration Test Suite for Instructor-to-Course Assignment in ContriGrade.

Covers:
1. TC-01: Coordinator assigns an instructor to a course section via Coordinator Dashboard.
2. TC-02: Instructor assignment validation (only users with role INSTRUCTOR are selectable).
3. TC-03: Coordinator clears / unassigns an instructor from a course section.
4. TC-04: Section creation with initial instructor assignment.
5. TC-05: Validation on section creation (duplicate section name rejected).
6. TC-06: Instructor Dashboard display (only assigned course sections are displayed for project creation).
7. TC-07: Student Courses page display (assigned instructor name vs TBA for unassigned).
8. TC-08: Role-based access control (RBAC) validation for coordinator assignment endpoints.
"""

import os
import sys
import time
import unittest
import uuid

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()

from django.db import transaction
from academic.models import Course, CourseSection, Project
from accounts.models import User

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "http://127.0.0.1:8000"


def get_driver(headless=True):
    """Factory to initialize Chrome WebDriver with optimal options."""
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=3")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver


def wait_for_element(driver, by, value, timeout=15):
    """Wait until an element is present and visible."""
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, value))
    )


def wait_for_text_in_element(driver, by, value, expected_text, timeout=15):
    """Wait until an element contains expected text."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            elem = driver.find_element(by, value)
            if expected_text.lower() in elem.text.lower():
                return elem
        except Exception:
            pass
        time.sleep(0.3)
    raise TimeoutError(f"Text '{expected_text}' not found in {by}={value} within {timeout}s")


class TestInstructorAssignmentSelenium(unittest.TestCase):
    """
    Selenium test suite for instructor-to-course assignment,
    validation, and multi-role display verification.
    """

    @classmethod
    def setUpClass(cls):
        """Ensure baseline test data exists for coordinators, instructors, courses, and sections."""
        # Ensure test coordinator exists
        cls.coord_email = "alok@gmail.com"
        cls.password = "123"
        cls.coordinator = User.objects.filter(email=cls.coord_email).first()
        if not cls.coordinator:
            cls.coordinator = User.objects.create_user(
                email=cls.coord_email,
                name="alok",
                role=User.Role.COORDINATOR,
                password=cls.password
            )

        # Ensure instructors exist
        cls.instructor_1 = User.objects.filter(role=User.Role.INSTRUCTOR).first()
        cls.instructor_2 = User.objects.filter(role=User.Role.INSTRUCTOR).exclude(user_id=cls.instructor_1.user_id if cls.instructor_1 else None).first()
        if not cls.instructor_1:
            cls.instructor_1 = User.objects.create_user(
                email="test_inst1@example.com",
                name="Test Instructor 1",
                role=User.Role.INSTRUCTOR,
                password=cls.password
            )
        if not cls.instructor_2:
            cls.instructor_2 = User.objects.create_user(
                email="test_inst2@example.com",
                name="Test Instructor 2",
                role=User.Role.INSTRUCTOR,
                password=cls.password
            )

        # Ensure student exists
        cls.student = User.objects.filter(role=User.Role.STUDENT).first()
        if not cls.student:
            cls.student = User.objects.create_user(
                email="test_student@example.com",
                name="Test Student",
                role=User.Role.STUDENT,
                password=cls.password
            )

        # Ensure a test course exists
        cls.course = Course.objects.first()
        if not cls.course:
            cls.course = Course.objects.create(
                course_code="CSE 999",
                course_name="Software Testing Lab",
                coordinator=cls.coordinator
            )

        # Ensure at least two test sections exist
        cls.section_1 = CourseSection.objects.filter(course=cls.course).first()
        if not cls.section_1:
            cls.section_1 = CourseSection.objects.create(
                course=cls.course,
                section_name="Section Alpha",
                instructor=cls.instructor_1
            )

        cls.section_2 = CourseSection.objects.filter(course=cls.course).exclude(section_id=cls.section_1.section_id).first()
        if not cls.section_2:
            cls.section_2 = CourseSection.objects.create(
                course=cls.course,
                section_name="Section Beta",
                instructor=None
            )

        # Enforce student enrollment in section_1
        cls.section_1.students.add(cls.student)

    def setUp(self):
        self.driver = get_driver(headless=True)
        self.wait = WebDriverWait(self.driver, 15)

    def tearDown(self):
        if self.driver:
            self.driver.quit()

    def _login(self, email, password=None):
        """Helper to log in a user and wait for redirection."""
        if password is None:
            password = self.password
        self.driver.get(f"{BASE_URL}/accounts/login/")
        user_field = wait_for_element(self.driver, By.NAME, "username")
        pass_field = self.driver.find_element(By.NAME, "password")
        submit_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")

        user_field.clear()
        user_field.send_keys(email)
        pass_field.clear()
        pass_field.send_keys(password)
        submit_btn.click()

        self.wait.until(lambda d: "/accounts/login/" not in d.current_url)

    # =========================================================================
    # TC-01: Coordinator Assigns Instructor to Course Section via Dashboard
    # =========================================================================
    def test_01_coordinator_assigns_instructor_via_dashboard(self):
        """
        Verify that a coordinator can assign an instructor to a section from the
        Coordinator Dashboard, and that the assigned instructor is immediately
        selected and displayed in the UI.
        """
        print("\n[TC-01] Testing Coordinator assigns instructor to section via Dashboard...")
        self._login(self.coord_email)

        coord_url = f"{BASE_URL}/academic/coordinator/dashboard/"
        self.driver.get(coord_url)
        self.wait.until(lambda d: "/coordinator/dashboard/" in d.current_url)

        # Find the form for section_2
        form_xpath = f"//form[contains(@action, '/academic/coordinator/sections/{self.section_2.section_id}/assign/')]"
        section_form = wait_for_element(self.driver, By.XPATH, form_xpath)

        instructor_select = Select(section_form.find_element(By.NAME, "instructor"))
        target_instructor_name = self.instructor_2.name
        instructor_select.select_by_visible_text(target_instructor_name)

        # Click the Update button inside that specific section form
        update_btn = section_form.find_element(By.XPATH, ".//button[@type='submit']")
        update_btn.click()

        # Wait for old form to become stale, ensuring page reload has occurred
        self.wait.until(EC.staleness_of(section_form))
        reloaded_form = self.wait.until(EC.presence_of_element_located((By.XPATH, form_xpath)))

        # Verification 1 (Display): Instructor select dropdown now shows target instructor as selected
        updated_select = Select(reloaded_form.find_element(By.NAME, "instructor"))
        selected_option = updated_select.first_selected_option

        self.assertEqual(
            selected_option.text.strip(),
            target_instructor_name,
            f"Expected selected instructor to be '{target_instructor_name}', but got '{selected_option.text.strip()}'"
        )
        print(f"  -> UI Display Verified: '{selected_option.text.strip()}' is selected.")

        # Verification 2 (Database): CourseSection in DB has the assigned instructor
        self.section_2.refresh_from_db()
        self.assertEqual(
            self.section_2.instructor,
            self.instructor_2,
            f"DB check failed: expected instructor {self.instructor_2}, got {self.section_2.instructor}"
        )
        print(f"  -> Database Verified: Section {self.section_2.section_name} assigned to {self.instructor_2.name}.")
        print("  -> [PASSED] TC-01: Coordinator Assigns Instructor via Dashboard")

    # =========================================================================
    # TC-02: Instructor Assignment Validation - Dropdown Options Filtering
    # =========================================================================
    def test_02_instructor_dropdown_validation_only_instructors_allowed(self):
        """
        Verify validation of selectable users: Only users with role='INSTRUCTOR'
        should appear in the assignment dropdown. Students, admins, and coordinators
        must NOT appear.
        """
        print("\n[TC-02] Testing Instructor assignment validation (role filtering)...")
        self._login(self.coord_email)

        # 1. Check Coordinator Dashboard select options
        coord_url = f"{BASE_URL}/academic/coordinator/dashboard/"
        self.driver.get(coord_url)
        form_xpath = f"//form[contains(@action, '/academic/coordinator/sections/{self.section_1.section_id}/assign/')]"
        section_form = wait_for_element(self.driver, By.XPATH, form_xpath)

        select_elem = Select(section_form.find_element(By.NAME, "instructor"))
        option_texts = [opt.text.strip() for opt in select_elem.options]
        option_values = [opt.get_attribute("value") for opt in select_elem.options]

        print(f"  -> Available options in Dashboard dropdown: {option_texts}")

        # Ensure empty/unassigned option exists
        self.assertIn("-- Select Instructor --", option_texts)

        # Ensure all active instructors are present
        all_instructors = User.objects.filter(role=User.Role.INSTRUCTOR)
        for inst in all_instructors:
            self.assertIn(inst.name, option_texts, f"Instructor '{inst.name}' should be in dropdown")
            self.assertIn(str(inst.user_id), option_values)

        # Ensure students and coordinators are NOT present in the dropdown options
        non_instructors = User.objects.exclude(role=User.Role.INSTRUCTOR)
        for user in non_instructors:
            self.assertNotIn(
                str(user.user_id),
                option_values,
                f"Non-instructor user '{user.name}' ({user.role}) should NOT be an assignment option"
            )

        # 2. Check Section Create page select options as well
        create_url = f"{BASE_URL}/academic/coordinator/sections/create/"
        self.driver.get(create_url)
        inst_create_select = Select(wait_for_element(self.driver, By.ID, "id_instructor"))
        create_option_values = [opt.get_attribute("value") for opt in inst_create_select.options]

        for user in non_instructors:
            self.assertNotIn(
                str(user.user_id),
                create_option_values,
                f"Non-instructor user '{user.name}' ({user.role}) should NOT be in Section Create instructor options"
            )

        print("  -> [PASSED] TC-02: Role Validation strictly excludes non-instructors from assignment")

    # =========================================================================
    # TC-03: Coordinator Clears / Unassigns Instructor from Section
    # =========================================================================
    def test_03_coordinator_unassigns_instructor(self):
        """
        Verify that a coordinator can unassign an instructor from a course section
        by selecting '-- Select Instructor --' (empty value) and saving.
        """
        print("\n[TC-03] Testing Coordinator unassigns instructor from section...")
        # Ensure section_1 has an instructor assigned initially
        self.section_1.instructor = self.instructor_1
        self.section_1.save()

        self._login(self.coord_email)
        coord_url = f"{BASE_URL}/academic/coordinator/dashboard/"
        self.driver.get(coord_url)

        form_xpath = f"//form[contains(@action, '/academic/coordinator/sections/{self.section_1.section_id}/assign/')]"
        section_form = wait_for_element(self.driver, By.XPATH, form_xpath)

        instructor_select = Select(section_form.find_element(By.NAME, "instructor"))
        # Select empty option: '-- Select Instructor --'
        instructor_select.select_by_value("")

        update_btn = section_form.find_element(By.XPATH, ".//button[@type='submit']")
        update_btn.click()

        # Wait for old form to become stale, ensuring page reload has occurred
        self.wait.until(EC.staleness_of(section_form))
        reloaded_form = self.wait.until(EC.presence_of_element_located((By.XPATH, form_xpath)))

        # Verification 1 (Display): Selected option is now '-- Select Instructor --'
        updated_select = Select(reloaded_form.find_element(By.NAME, "instructor"))
        self.assertEqual(
            updated_select.first_selected_option.text.strip(),
            "-- Select Instructor --",
            "Expected dropdown to display '-- Select Instructor --' as selected"
        )
        print("  -> UI Display Verified: '-- Select Instructor --' is displayed.")

        # Verification 2 (Database): CourseSection instructor is None
        self.section_1.refresh_from_db()
        self.assertIsNone(
            self.section_1.instructor,
            "CourseSection instructor should be None in DB after unassigning"
        )
        print("  -> Database Verified: Section instructor is None.")
        print("  -> [PASSED] TC-03: Coordinator Unassigns Instructor")

    # =========================================================================
    # TC-04: Section Creation with Initial Instructor Assignment
    # =========================================================================
    def test_04_create_section_with_instructor_assignment(self):
        """
        Verify that a coordinator can create a new course section while simultaneously
        assigning an instructor, and that the assignment is correctly saved and displayed.
        """
        print("\n[TC-04] Testing Section creation with instructor assignment...")
        unique_suffix = uuid.uuid4().hex[:6]
        new_section_name = f"Sec-{unique_suffix}"

        self._login(self.coord_email)
        create_url = f"{BASE_URL}/academic/coordinator/sections/create/"
        self.driver.get(create_url)

        wait_for_element(self.driver, By.ID, "id_course")

        course_select = Select(self.driver.find_element(By.ID, "id_course"))
        course_select.select_by_value(str(self.course.course_id))

        name_input = self.driver.find_element(By.ID, "id_section_name")
        name_input.clear()
        name_input.send_keys(new_section_name)

        instructor_select = Select(self.driver.find_element(By.ID, "id_instructor"))
        instructor_select.select_by_value(str(self.instructor_1.user_id))

        save_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Save Section')]")
        save_btn.click()

        # Should redirect to Coordinator Dashboard
        self.wait.until(lambda d: "/coordinator/dashboard/" in d.current_url)

        # Verification 1 (Display): New section appears under Course Sections & Instructors
        body_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn(new_section_name, body_text, f"Section '{new_section_name}' should appear on dashboard")

        # Verification 2 (Database & UI form): Check the created section
        created_section = CourseSection.objects.filter(course=self.course, section_name=new_section_name).first()
        self.assertIsNotNone(created_section, "Created section was not found in DB")
        self.assertEqual(created_section.instructor, self.instructor_1)

        # Check that its dropdown on the dashboard has instructor_1 selected
        form_xpath = f"//form[contains(@action, '/academic/coordinator/sections/{created_section.section_id}/assign/')]"
        sec_form = self.driver.find_element(By.XPATH, form_xpath)
        sec_select = Select(sec_form.find_element(By.NAME, "instructor"))
        self.assertEqual(sec_select.first_selected_option.text.strip(), self.instructor_1.name)

        print(f"  -> Section '{new_section_name}' successfully created and assigned to {self.instructor_1.name}.")

        # Cleanup created section
        created_section.delete()
        print("  -> [PASSED] TC-04: Section Creation with Instructor Assignment")

    # =========================================================================
    # TC-05: Validation on Section Creation (Duplicate Section Prevention)
    # =========================================================================
    def test_05_section_creation_validation_duplicate_prevention(self):
        """
        Verify validation error handling when trying to create a section with a name
        that already exists for the course (unique_together constraint validation).
        """
        print("\n[TC-05] Testing duplicate section validation on creation...")
        self._login(self.coord_email)
        create_url = f"{BASE_URL}/academic/coordinator/sections/create/"
        self.driver.get(create_url)

        wait_for_element(self.driver, By.ID, "id_course")

        course_select = Select(self.driver.find_element(By.ID, "id_course"))
        course_select.select_by_value(str(self.course.course_id))

        # Enter existing section name
        name_input = self.driver.find_element(By.ID, "id_section_name")
        name_input.clear()
        name_input.send_keys(self.section_1.section_name)

        form_elem = self.driver.find_element(By.TAG_NAME, "form")
        save_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Save Section')]")
        save_btn.click()

        # Wait for form reload
        self.wait.until(EC.staleness_of(form_elem))

        # Should remain on the creation page (not redirected to dashboard)
        self.assertIn("/academic/coordinator/sections/create/", self.driver.current_url)

        # Validation error message should be displayed in the error container
        error_box = wait_for_element(self.driver, By.XPATH, "//div[contains(@class, 'bg-red-50')]")
        error_text = error_box.text.lower()
        self.assertTrue(
            "already exists" in error_text or "error" in error_text,
            f"Expected duplicate section validation error, got: '{error_box.text}'"
        )
        print(f"  -> Validation Error Detected: '{error_box.text.strip()}'")
        print("  -> [PASSED] TC-05: Duplicate Section Validation")

    # =========================================================================
    # TC-06: Instructor Dashboard Display of Assigned Course Sections
    # =========================================================================
    def test_06_instructor_dashboard_displays_only_assigned_sections(self):
        """
        Verify that on the Instructor Dashboard, an instructor ONLY sees course
        sections assigned to them in the project creation form dropdown.
        Unassigned sections or sections assigned to other instructors must not be visible.
        """
        print("\n[TC-06] Testing Instructor Dashboard display of assigned sections...")
        # Assign section_1 to instructor_1, and ensure section_2 is NOT assigned to instructor_1
        self.section_1.instructor = self.instructor_1
        self.section_1.save()

        self.section_2.instructor = self.instructor_2
        self.section_2.save()

        # Log in as instructor_1
        self._login(self.instructor_1.email)

        # Navigate to dashboard
        self.driver.get(f"{BASE_URL}/academic/dashboard/")
        self.wait.until(lambda d: "/academic/" in d.current_url)

        # Check section dropdown in ProjectForm
        section_select_elem = wait_for_element(self.driver, By.NAME, "section")
        section_select = Select(section_select_elem)
        available_section_texts = [opt.text.strip() for opt in section_select.options]

        print(f"  -> Instructor available section options: {available_section_texts}")

        # Assigned section MUST be present
        self.assertTrue(
            any(self.section_1.section_name in text for text in available_section_texts),
            f"Assigned section '{self.section_1.section_name}' must be selectable by instructor"
        )

        # Section assigned to another instructor MUST NOT be present
        self.assertFalse(
            any(self.section_2.section_name in text for text in available_section_texts),
            f"Unassigned/other section '{self.section_2.section_name}' should NOT be visible to this instructor"
        )
        print("  -> [PASSED] TC-06: Instructor Dashboard correctly restricts sections to assigned faculty")

    # =========================================================================
    # TC-07: Student Courses Page Display of Assigned Instructor vs TBA
    # =========================================================================
    def test_07_student_courses_page_displays_assigned_instructor_and_tba(self):
        """
        Verify that enrolled students see the assigned instructor's name on their
        'My Courses' page, and see 'Instructor: TBA' when no instructor is assigned.
        """
        print("\n[TC-07] Testing Student Courses display of assigned instructor vs TBA...")
        # Case A: Section has assigned instructor
        self.section_1.instructor = self.instructor_1
        self.section_1.save()
        self.section_1.students.add(self.student)

        self._login(self.student.email)

        courses_url = f"{BASE_URL}/academic/student/courses/"
        self.driver.get(courses_url)
        self.wait.until(lambda d: "/student/courses/" in d.current_url)

        body_text = wait_for_element(self.driver, By.TAG_NAME, "body").text
        expected_instructor_str = f"Instructor: {self.instructor_1.name}"
        self.assertIn(
            expected_instructor_str,
            body_text,
            f"Expected student page to display '{expected_instructor_str}'"
        )
        print(f"  -> Student View Verified: '{expected_instructor_str}' is visible.")

        # Case B: Section has NO assigned instructor (Unassigned / TBA)
        self.section_1.instructor = None
        self.section_1.save()

        self.driver.refresh()
        self.wait.until(lambda d: "/student/courses/" in d.current_url)
        body_text_unassigned = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn(
            "Instructor: TBA",
            body_text_unassigned,
            "Expected student page to display 'Instructor: TBA' when unassigned"
        )
        print("  -> Student View Verified: 'Instructor: TBA' is displayed when unassigned.")

        # Restore assignment
        self.section_1.instructor = self.instructor_1
        self.section_1.save()
        print("  -> [PASSED] TC-07: Student Courses page display verified")

    # =========================================================================
    # TC-08: Security & Role-Based Access Validation
    # =========================================================================
    def test_08_rbac_unauthorized_user_cannot_access_coordinator_assignment(self):
        """
        Verify that unauthorized roles (e.g. Student) are blocked from accessing
        the Coordinator Dashboard and section management endpoints.
        """
        print("\n[TC-08] Testing RBAC: Student blocked from coordinator assignment...")
        self._login(self.student.email)

        # 1. Attempt to access coordinator dashboard
        self.driver.get(f"{BASE_URL}/academic/coordinator/dashboard/")
        self.wait.until(lambda d: "/coordinator/dashboard/" not in d.current_url)
        self.assertNotIn("/academic/coordinator/dashboard/", self.driver.current_url)
        print(f"  -> Access to Coordinator Dashboard denied, redirected to: {self.driver.current_url}")

        # 2. Attempt to access section create
        self.driver.get(f"{BASE_URL}/academic/coordinator/sections/create/")
        self.wait.until(lambda d: "/coordinator/sections/create/" not in d.current_url)
        self.assertNotIn("/academic/coordinator/sections/create/", self.driver.current_url)
        print(f"  -> Access to Section Create denied, redirected to: {self.driver.current_url}")

        print("  -> [PASSED] TC-08: Security & RBAC access control verified")


if __name__ == '__main__':
    print("=" * 75)
    print(" ContriGrade Instructor-to-Course Assignment Selenium Test Suite")
    print("=" * 75)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestInstructorAssignmentSelenium)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(not result.wasSuccessful())
