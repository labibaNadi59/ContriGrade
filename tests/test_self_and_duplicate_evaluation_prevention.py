
import os
import sys
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, Client
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from django.contrib.messages import get_messages
from django.db import IntegrityError

from accounts.models import User
from academic.models import (
    Course, CourseSection, Project, Team, TeamMember,
    EvaluationCriterion, PeerEvaluation, PeerEvaluationScore
)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# =====================================================================
# SHARED BASE FIXTURE
# =====================================================================
class SelfAndDuplicateBaseTestCase(TestCase):
    """Common setup for self-evaluation and duplicate-evaluation prevention tests."""

    def setUp(self):
        super().setUp()
        self.coordinator = User.objects.create_user(
            email="coord_sd@test.com",
            name="Coordinator Davis",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_sd@test.com",
            name="Dr. Sarah Jenkins",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.alice = User.objects.create_user(
            email="alice_sd@test.com",
            name="Alice Evaluator",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.bob = User.objects.create_user(
            email="bob_sd@test.com",
            name="Bob Evaluatee",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.charlie = User.objects.create_user(
            email="charlie_sd@test.com",
            name="Charlie Teammate",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.alice, self.bob, self.charlie)

        self.project = Project.objects.create(
            section=self.section,
            title="Peer Evaluation Guard Project",
            description="Testing evaluation integrity controls",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Integrity Squad",
            github_repo_url="https://github.com/contrigrade/sample-repo"
        )
        TeamMember.objects.create(team=self.team, user=self.alice)
        TeamMember.objects.create(team=self.team, user=self.bob)
        TeamMember.objects.create(team=self.team, user=self.charlie)

        self.patcher = patch('academic.views.fetch_team_commits')
        self.mock_fetch = self.patcher.start()
        self.mock_fetch.return_value = {
            'status': 'success',
            'total_commits': 0,
            'total_branches': 1,
            'commits': []
        }
        self.addCleanup(self.patcher.stop)

        self.crit1 = EvaluationCriterion.objects.create(
            project=self.project,
            name="Technical Contribution",
            description="Architecture and code quality",
            max_score=5
        )
        self.crit2 = EvaluationCriterion.objects.create(
            project=self.project,
            name="Team Collaboration",
            description="Communication and responsiveness",
            max_score=5
        )

        self.self_eval_url = f"/academic/student/team/{self.team.team_id}/evaluate/{self.alice.pk}/"
        self.bob_eval_url = f"/academic/student/team/{self.team.team_id}/evaluate/{self.bob.pk}/"
        self.charlie_eval_url = f"/academic/student/team/{self.team.team_id}/evaluate/{self.charlie.pk}/"
        self.progress_url = f"/academic/student/team/{self.team.team_id}/progress/"


# =====================================================================
# 1. SELF-EVALUATION PREVENTION TESTS
# =====================================================================
class SelfEvaluationPreventionTests(SelfAndDuplicateBaseTestCase):
    """Verifies that attempts at self-evaluation are strictly blocked with appropriate messages."""

    def test_get_self_evaluation_url_blocked_with_error_message(self):
        """Direct GET request to evaluate oneself redirects to team progress with error message."""
        self.client.force_login(self.alice)
        resp = self.client.get(self.self_eval_url, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertRedirects(resp, self.progress_url)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("You cannot evaluate yourself.", messages)

    def test_post_self_evaluation_blocked_with_error_message(self):
        """POST request attempting to submit self-evaluation redirects with error message."""
        self.client.force_login(self.alice)
        post_data = {
            f'criterion_{self.crit1.pk}': '5',
            f'criterion_{self.crit2.pk}': '5',
            'general_feedback': 'I did great work on this project.'
        }
        resp = self.client.post(self.self_eval_url, post_data, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertRedirects(resp, self.progress_url)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("You cannot evaluate yourself.", messages)

    def test_self_evaluation_creates_no_database_records(self):
        """Self-evaluation attempts do not persist any PeerEvaluation or PeerEvaluationScore records."""
        self.client.force_login(self.alice)
        post_data = {
            f'criterion_{self.crit1.pk}': '5',
            f'criterion_{self.crit2.pk}': '5',
            'general_feedback': 'Self appraisal'
        }
        self.client.post(self.self_eval_url, post_data)

        self.assertFalse(PeerEvaluation.objects.filter(evaluator=self.alice, evaluatee=self.alice).exists())
        self.assertEqual(PeerEvaluation.objects.count(), 0)
        self.assertEqual(PeerEvaluationScore.objects.count(), 0)

    def test_team_progress_ui_omits_evaluate_peer_link_on_self_row(self):
        """Team progress page displays 'You' badge on own row and omits any Evaluate Peer button."""
        self.client.force_login(self.alice)
        resp = self.client.get(self.progress_url)

        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Alice's row has You indicator
        self.assertIn(">You</span>", content)
        # Self-evaluation URL is completely absent from the markup
        self.assertNotIn(self.self_eval_url, content)

    def test_self_evaluation_blocked_for_all_team_members(self):
        """Bob and Charlie are equally blocked from evaluating themselves."""
        for user in [self.bob, self.charlie]:
            self.client.force_login(user)
            user_url = f"/academic/student/team/{self.team.team_id}/evaluate/{user.pk}/"
            resp = self.client.get(user_url, follow=True)

            self.assertEqual(resp.status_code, 200)
            messages = [m.message for m in get_messages(resp.wsgi_request)]
            self.assertIn("You cannot evaluate yourself.", messages)
            self.assertFalse(PeerEvaluation.objects.filter(evaluator=user, evaluatee=user).exists())


# =====================================================================
# 2. DUPLICATE-EVALUATION PREVENTION TESTS
# =====================================================================
class DuplicateEvaluationPreventionTests(SelfAndDuplicateBaseTestCase):
    """Verifies that duplicate evaluations of the same teammate are blocked with appropriate messages."""

    def setUp(self):
        super().setUp()
        # Seed an initial valid evaluation from Alice to Bob
        self.initial_evaluation = PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.alice,
            evaluatee=self.bob,
            general_feedback="Initial feedback for Bob."
        )
        PeerEvaluationScore.objects.create(
            evaluation=self.initial_evaluation,
            criterion=self.crit1,
            score=4
        )
        PeerEvaluationScore.objects.create(
            evaluation=self.initial_evaluation,
            criterion=self.crit2,
            score=5
        )

    def test_duplicate_get_request_blocked_with_error_message(self):
        """Visiting evaluate page for an already evaluated teammate redirects with error message."""
        self.client.force_login(self.alice)
        resp = self.client.get(self.bob_eval_url, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertRedirects(resp, self.progress_url)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        expected_msg = f"You have already submitted an evaluation for {self.bob.name}."
        self.assertIn(expected_msg, messages)

    def test_duplicate_post_submission_blocked_with_error_message(self):
        """POSTing a second evaluation for the same teammate is blocked with error message."""
        self.client.force_login(self.alice)
        post_data = {
            f'criterion_{self.crit1.pk}': '1',
            f'criterion_{self.crit2.pk}': '1',
            'general_feedback': 'Changed my mind, low score.'
        }
        resp = self.client.post(self.bob_eval_url, post_data, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertRedirects(resp, self.progress_url)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        expected_msg = f"You have already submitted an evaluation for {self.bob.name}."
        self.assertIn(expected_msg, messages)

    def test_duplicate_submission_does_not_mutate_original_scores_or_feedback(self):
        """Duplicate submission attempt preserves the original evaluation intact."""
        self.client.force_login(self.alice)
        post_data = {
            f'criterion_{self.crit1.pk}': '1',
            f'criterion_{self.crit2.pk}': '1',
            'general_feedback': 'Changed my mind, low score.'
        }
        self.client.post(self.bob_eval_url, post_data)

        self.initial_evaluation.refresh_from_db()
        self.assertEqual(self.initial_evaluation.general_feedback, "Initial feedback for Bob.")
        self.assertEqual(PeerEvaluation.objects.filter(team=self.team, evaluator=self.alice, evaluatee=self.bob).count(), 1)

        scores = {s.criterion_id: s.score for s in self.initial_evaluation.scores.all()}
        self.assertEqual(scores[self.crit1.pk], 4)
        self.assertEqual(scores[self.crit2.pk], 5)

    def test_duplicate_evaluation_enforced_at_database_constraint_level(self):
        """Database unique_together constraint raises IntegrityError if bypass is attempted."""
        with self.assertRaises(IntegrityError):
            PeerEvaluation.objects.create(
                team=self.team,
                evaluator=self.alice,
                evaluatee=self.bob,
                general_feedback="Direct DB duplicate insertion"
            )

    def test_ui_transitions_to_evaluated_preventing_duplicate_actions(self):
        """On team progress, Bob's row displays 'Evaluated' badge and omits evaluate link."""
        self.client.force_login(self.alice)
        resp = self.client.get(self.progress_url)

        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Bob's row has Evaluated badge
        self.assertIn("Evaluated", content)
        self.assertIn("fa-check-circle", content)
        # Evaluate link for Bob is completely removed from markup
        self.assertNotIn(self.bob_eval_url, content)


# =====================================================================
# 3. EVALUATION INDEPENDENCE & BOUNDARY TESTS
# =====================================================================
class EvaluationIndependenceAndBoundaryTests(SelfAndDuplicateBaseTestCase):
    """Verifies that duplicate checks are correctly scoped and do not block legitimate evaluations."""

    def test_evaluating_teammate_bob_does_not_block_evaluating_charlie(self):
        """Alice evaluating Bob does not prevent Alice from evaluating Charlie."""
        # Alice evaluates Bob
        PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.alice,
            evaluatee=self.bob,
            general_feedback="Bob feedback"
        )

        # Alice now evaluates Charlie -> succeeds cleanly
        self.client.force_login(self.alice)
        post_data = {
            f'criterion_{self.crit1.pk}': '5',
            f'criterion_{self.crit2.pk}': '4',
            'general_feedback': 'Charlie did great too.'
        }
        resp = self.client.post(self.charlie_eval_url, post_data, follow=True)

        self.assertEqual(resp.status_code, 200)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn(f"Anonymous evaluation for {self.charlie.name} submitted successfully.", messages)
        self.assertTrue(PeerEvaluation.objects.filter(team=self.team, evaluator=self.alice, evaluatee=self.charlie).exists())

    def test_evaluating_bob_by_alice_does_not_block_charlie_from_evaluating_bob(self):
        """Multiple distinct teammates can each evaluate Bob once without conflict."""
        # Alice evaluates Bob
        PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.alice,
            evaluatee=self.bob,
            general_feedback="Alice on Bob"
        )

        # Charlie evaluates Bob -> succeeds cleanly
        self.client.force_login(self.charlie)
        post_data = {
            f'criterion_{self.crit1.pk}': '4',
            f'criterion_{self.crit2.pk}': '4',
            'general_feedback': 'Charlie on Bob'
        }
        resp = self.client.post(self.bob_eval_url, post_data, follow=True)

        self.assertEqual(resp.status_code, 200)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn(f"Anonymous evaluation for {self.bob.name} submitted successfully.", messages)
        self.assertEqual(PeerEvaluation.objects.filter(team=self.team, evaluatee=self.bob).count(), 2)

    def test_validation_failure_retry_is_not_treated_as_duplicate(self):
        """If submission fails validation (e.g. missing criterion), subsequent valid submission is permitted."""
        self.client.force_login(self.alice)

        # 1. First attempt fails validation (missing crit2)
        resp_fail = self.client.post(self.bob_eval_url, {
            f'criterion_{self.crit1.pk}': '5'
        }, follow=True)
        self.assertFalse(PeerEvaluation.objects.filter(team=self.team, evaluator=self.alice, evaluatee=self.bob).exists())

        # 2. Resubmission with all criteria succeeds without false duplicate trigger
        resp_success = self.client.post(self.bob_eval_url, {
            f'criterion_{self.crit1.pk}': '5',
            f'criterion_{self.crit2.pk}': '5',
            'general_feedback': 'Corrected form'
        }, follow=True)

        self.assertEqual(resp_success.status_code, 200)
        messages = [m.message for m in get_messages(resp_success.wsgi_request)]
        self.assertIn(f"Anonymous evaluation for {self.bob.name} submitted successfully.", messages)
        self.assertTrue(PeerEvaluation.objects.filter(team=self.team, evaluator=self.alice, evaluatee=self.bob).exists())


# =====================================================================
# 4. LIVE SELENIUM BROWSER E2E TESTS (HEADLESS CHROME)
# =====================================================================
class SelfAndDuplicatePreventionSeleniumE2ETests(StaticLiveServerTestCase):
    """End-to-end browser test verifying UI enforcement and URL blocking for self and duplicate evaluations."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--log-level=3")

        service = Service(ChromeDriverManager().install())
        cls.driver = webdriver.Chrome(service=service, options=options)
        cls.wait = WebDriverWait(cls.driver, 20)

    @classmethod
    def tearDownClass(cls):
        if cls.driver:
            cls.driver.quit()
        super().tearDownClass()

    def setUp(self):
        self.coordinator = User.objects.create_user(
            email="coord_se_sd@test.com",
            name="Coord SE",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_se_sd@test.com",
            name="Dr. Jenkins",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.alice = User.objects.create_user(
            email="alice_se_sd@test.com",
            name="Alice Evaluator",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.bob = User.objects.create_user(
            email="bob_se_sd@test.com",
            name="Bob Evaluatee",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE314",
            course_name="Software Engineering",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Section A",
            instructor=self.instructor
        )
        self.section.students.add(self.alice, self.bob)

        self.project = Project.objects.create(
            section=self.section,
            title="Integrity E2E Project",
            description="Testing live self and duplicate prevention",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Guard Squad",
            github_repo_url="https://github.com/contrigrade/sample-repo"
        )
        TeamMember.objects.create(team=self.team, user=self.alice)
        TeamMember.objects.create(team=self.team, user=self.bob)

        self.patcher = patch('academic.views.fetch_team_commits')
        self.mock_fetch = self.patcher.start()
        self.mock_fetch.return_value = {
            'status': 'success',
            'total_commits': 0,
            'total_branches': 1,
            'commits': []
        }
        self.addCleanup(self.patcher.stop)

        self.crit = EvaluationCriterion.objects.create(
            project=self.project,
            name="Delivery Quality",
            description="Overall delivery standard",
            max_score=5
        )

    def _login(self, email, password):
        self.driver.get(f"{self.live_server_url}/accounts/login/")
        user_field = self.wait.until(EC.presence_of_element_located((By.NAME, "username")))
        pass_field = self.driver.find_element(By.NAME, "password")
        submit_btn = self.driver.find_element(By.XPATH, "//button[@type='submit']")

        user_field.clear()
        user_field.send_keys(email)
        pass_field.clear()
        pass_field.send_keys(password)
        submit_btn.click()
        self.wait.until(lambda d: "/accounts/login/" not in d.current_url)

    def test_e2e_self_and_duplicate_evaluation_prevention(self):
        """Live browser workflow:
        1. Alice logs in -> visits team progress.
        2. Alice confirms her row has 'You' badge and NO 'Evaluate Peer' button.
        3. Alice manually enters URL to evaluate herself -> blocked with 'You cannot evaluate yourself.'
        4. Alice clicks 'Evaluate Peer' for Bob -> submits evaluation successfully.
        5. Alice verifies Bob's row now shows 'Evaluated' badge and NO 'Evaluate Peer' button.
        6. Alice manually enters URL to evaluate Bob again -> blocked with 'You have already submitted an evaluation for Bob Evaluatee.'
        """
        progress_url = f"{self.live_server_url}/academic/student/team/{self.team.team_id}/progress/"
        self_eval_url = f"{self.live_server_url}/academic/student/team/{self.team.team_id}/evaluate/{self.alice.pk}/"
        bob_eval_url = f"{self.live_server_url}/academic/student/team/{self.team.team_id}/evaluate/{self.bob.pk}/"

        # 1. Login as Alice
        self._login("alice_se_sd@test.com", "password123")
        self.driver.get(progress_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(., 'Team Progress')]")))

        # 2. Check UI for self: 'You' badge is present
        page_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("YOU", page_text.upper())
        self.assertEqual(len(self.driver.find_elements(By.XPATH, f"//a[contains(@href, '/evaluate/{self.alice.pk}/')]")), 0)

        # 3. Direct attempt to evaluate oneself via URL
        self.driver.get(self_eval_url)
        # Redirected back to progress with error
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'You cannot evaluate yourself.')]")))
        self.assertIn("/progress/", self.driver.current_url)

        # 4. Valid evaluation of Bob
        eval_bob_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, f"//a[contains(@href, '/evaluate/{self.bob.pk}/')]")))
        eval_bob_btn.click()

        # Fill and submit evaluation form for Bob
        self.wait.until(EC.presence_of_element_located((By.NAME, f"criterion_{self.crit.pk}")))
        score_select = Select(self.driver.find_element(By.NAME, f"criterion_{self.crit.pk}"))
        score_select.select_by_value("5")

        feedback_input = self.driver.find_element(By.NAME, "general_feedback")
        feedback_input.send_keys("E2E legitimate evaluation of Bob.")

        submit_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Submit Anonymous Evaluation')]")
        submit_btn.click()

        # 5. Redirected to progress page with success message
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'submitted successfully')]")))
        progress_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Evaluated", progress_text)

        # Confirm Evaluate Peer button for Bob is gone
        bob_eval_links = self.driver.find_elements(By.XPATH, f"//a[contains(@href, '/evaluate/{self.bob.pk}/')]")
        self.assertEqual(len(bob_eval_links), 0)

        # 6. Direct attempt to evaluate Bob a second time via URL
        self.driver.get(bob_eval_url)
        # Redirected back to progress with duplicate error message
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'You have already submitted an evaluation for Bob Evaluatee.')]")))
        self.assertIn("/progress/", self.driver.current_url)

