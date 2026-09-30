
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


def test_valid_login():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    try:
        # Open the login page
        driver.get("http://127.0.0.1:8000/accounts/login/")

        # Enter valid email
        driver.find_element(
            By.NAME, "username"
        ).send_keys("sara@gmail.com")

        # Enter valid password
        driver.find_element(
            By.NAME, "password"
        ).send_keys("123")

        # Click the Sign In button
        driver.find_element(
            By.CSS_SELECTOR,
            "button[type='submit']"
        ).click()

        # Verify that login was successful
        assert "/accounts/login/" not in driver.current_url

    finally:
        # Close the browser
        driver.quit()


def test_invalid_login():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    try:
        # Open the login page
        driver.get("http://127.0.0.1:8000/accounts/login/")

        # Enter invalid email
        driver.find_element(
            By.NAME, "username"
        ).send_keys("wrong@example.com")

        # Enter invalid password
        driver.find_element(
            By.NAME, "password"
        ).send_keys("wrongpassword")

        # Click the Sign In button
        driver.find_element(
            By.CSS_SELECTOR,
            "button[type='submit']"
        ).click()

        # Verify that login failed
        assert "/accounts/login/" in driver.current_url

    finally:
        # Close the browser
        driver.quit()


def test_logout():

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )

    try:
        # Open login page
        driver.get("http://127.0.0.1:8000/accounts/login/")

        # Enter valid email
        driver.find_element(
            By.NAME, "username"
        ).send_keys("sara@gmail.com")

        # Enter valid password
        driver.find_element(
            By.NAME, "password"
        ).send_keys("123")

        # Click Sign In
        driver.find_element(
            By.CSS_SELECTOR,
            "button[type='submit']"
        ).click()

        # Wait for dashboard
        time.sleep(2)

        # Verify login was successful
        assert "/accounts/login/" not in driver.current_url

        # Find and click Sign Out
        driver.find_element(
            By.XPATH,
            "//button[.//span[normalize-space()='Sign Out']]"
        ).click()

        # Wait for logout
        time.sleep(2)

        # Verify user returned to login page
        assert "/accounts/login/" in driver.current_url

    finally:
        driver.quit()