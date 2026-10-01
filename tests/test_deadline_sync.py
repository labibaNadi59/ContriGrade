from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime
import re
import time


def test_deadline_sync_across_views():

    # =====================================================
    # INSTRUCTOR BROWSER
    # =====================================================

    instructor_driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    instructor_wait = WebDriverWait(instructor_driver, 10)

    try:

        print("\n==============================")
        print("INSTRUCTOR TEST")
        print("==============================")

        # Instructor Login
        instructor_driver.get(
            "http://127.0.0.1:8000/accounts/login/"
        )

        username = instructor_wait.until(
            EC.presence_of_element_located(
                (By.NAME, "username")
            )
        )

        password = instructor_wait.until(
            EC.presence_of_element_located(
                (By.NAME, "password")
            )
        )

        username.send_keys("tanjina@gmail.com")
        password.send_keys("123")
        password.submit()

        time.sleep(2)

        print("Instructor login successful")

        # Instructor Dashboard
        instructor_driver.get(
            "http://127.0.0.1:8000/academic/dashboard/"
        )

        time.sleep(2)

        print("Instructor dashboard opened")

        instructor_page_text = instructor_driver.find_element(
            By.TAG_NAME,
            "body"
        ).text

        # Find CSE 314 deadline
        instructor_pattern = (
            r"CSE 314\s+"
            r"cse314 - section B\s+"
            r"Deadline:\s*"
            r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}\s+"
            r"\d{1,2}:\d{2}\s+[AP]M)"
        )

        instructor_match = re.search(
            instructor_pattern,
            instructor_page_text
        )

        assert instructor_match is not None, (
            "CSE 314 deadline not found in Instructor view"
        )

        instructor_deadline_text = instructor_match.group(1)

        print(
            "Instructor CSE 314 Deadline:",
            instructor_deadline_text
        )

        instructor_deadline = datetime.strptime(
            instructor_deadline_text,
            "%b %d, %Y %I:%M %p"
        )

        print(
            "Instructor Parsed Deadline:",
            instructor_deadline
        )


        # =====================================================
        # STUDENT BROWSER
        # =====================================================

        print("\n==============================")
        print("STUDENT TEST")
        print("==============================")

        student_driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install())
        )

        student_wait = WebDriverWait(student_driver, 10)

        try:

            # Student Login
            student_driver.get(
                "http://127.0.0.1:8000/accounts/login/"
            )

            username = student_wait.until(
                EC.presence_of_element_located(
                    (By.NAME, "username")
                )
            )

            password = student_wait.until(
                EC.presence_of_element_located(
                    (By.NAME, "password")
                )
            )

            username.send_keys("tia@gmail.com")
            password.send_keys("123")
            password.submit()

            time.sleep(2)

            print("Student login successful")

            # Student Dashboard
            student_driver.get(
                "http://127.0.0.1:8000/academic/student/dashboard/"
            )

            time.sleep(2)

            print("Student dashboard opened")

            student_page_text = student_driver.find_element(
                By.TAG_NAME,
                "body"
            ).text

            # Find CSE 314 deadline
            student_pattern = (
                r"CSE 314\s+"
                r"Deadline:\s*"
                r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}\s+"
                r"\d{1,2}:\d{2}\s+[AP]M)"
            )

            student_match = re.search(
                student_pattern,
                student_page_text
            )

            assert student_match is not None, (
                "CSE 314 deadline not found in Student view"
            )

            student_deadline_text = student_match.group(1)

            print(
                "Student CSE 314 Deadline:",
                student_deadline_text
            )

            try:

                student_deadline = datetime.strptime(
                    student_deadline_text,
                    "%B %d, %Y %I:%M %p"
                )

            except ValueError:

                student_deadline = datetime.strptime(
                    student_deadline_text,
                    "%b %d, %Y %I:%M %p"
                )

            print(
                "Student Parsed Deadline:",
                student_deadline
            )


            # =================================================
            # COMPARE
            # =================================================

            print("\n==============================")
            print("COMPARING DEADLINES")
            print("==============================")

            print(
                "Instructor:",
                instructor_deadline
            )

            print(
                "Student:",
                student_deadline
            )

            assert instructor_deadline == student_deadline, (
                f"Deadline mismatch! "
                f"Instructor: {instructor_deadline}, "
                f"Student: {student_deadline}"
            )

            print("\n==============================================")
            print("SUCCESS: Deadline is synchronized!")
            print("==============================================")


        finally:

            student_driver.quit()
            print("Student browser closed.")


    finally:

        instructor_driver.quit()
        print("Instructor browser closed.")