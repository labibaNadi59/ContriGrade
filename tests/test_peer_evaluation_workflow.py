

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
class PeerEvaluationBaseTestCase(TestCase):
    """Common setup for peer evaluation tests."""

    def setUp(self):
        super().setUp()
        self.coordinator = User.objects.create_user(
            email="coord_pe@test.com",
            name="Coordinator Vance",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_pe@test.com",
            name="Dr. Aris Thorne",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.alice = User.objects.create_user(
            email="alice_pe@test.com",
            name="Alice Evaluator",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.bob = User.objects.create_user(
            email="bob_pe@test.com",
            name="Bob Evaluatee",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.charlie = User.objects.create_user(
            email="charlie_pe@test.com",
            name="Charlie Teammate",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.outsider = User.objects.create_user(
            email="outsider_pe@test.com",
            name="David Outsider",
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
        self.section.students.add(self.alice, self.bob, self.charlie, self.outsider)

        self.project = Project.objects.create(
            section=self.section,
            title="Peer Assessment Platform",
            description="Collaborative engineering project",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Core Engineers",
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

        # Configure 2 criteria for this project
        self.crit_tech = EvaluationCriterion.objects.create(
            project=self.project,
            name="Technical Contribution",
            description="Quality and completeness of code and deliverables",
            max_score=5
        )
        self.crit_collab = EvaluationCriterion.objects.create(
            project=self.project,
            name="Collaboration & Communication",
            description="Punctuality, team communication, and responsiveness",
            max_score=5
        )

        self.eval_url_bob = f"/academic/student/team/{self.team.team_id}/evaluate/{self.bob.pk}/"
        self.eval_url_charlie = f"/academic/student/team/{self.team.team_id}/evaluate/{self.charlie.pk}/"
        self.progress_url = f"/academic/student/team/{self.team.team_id}/progress/"


# =====================================================================
# 1. MODEL & STORAGE INTEGRITY TESTS
# =====================================================================
class PeerEvaluationModelAndStorageTests(PeerEvaluationBaseTestCase):
    """Unit tests for PeerEvaluation, PeerEvaluationScore, and DB constraints."""

    def test_peer_evaluation_and_scores_creation_and_storage(self):
        """Valid evaluation and score records are created with accurate associations."""
        eval_record = PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.alice,
            evaluatee=self.bob,
            general_feedback="Outstanding database architecture work."
        )
        score1 = PeerEvaluationScore.objects.create(
            evaluation=eval_record,
            criterion=self.crit_tech,
            score=5
        )
        score2 = PeerEvaluationScore.objects.create(
            evaluation=eval_record,
            criterion=self.crit_collab,
            score=4
        )

        self.assertIsNotNone(eval_record.pk)
        self.assertEqual(eval_record.team, self.team)
        self.assertEqual(eval_record.evaluator, self.alice)
        self.assertEqual(eval_record.evaluatee, self.bob)
        self.assertEqual(eval_record.general_feedback, "Outstanding database architecture work.")
        self.assertEqual(eval_record.scores.count(), 2)
        self.assertEqual(score1.score, 5)
        self.assertEqual(score2.score, 4)

    def test_unique_together_evaluator_evaluatee_per_team_enforced(self):
        """Database enforces unique_together on ('team', 'evaluator', 'evaluatee')."""
        PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.alice,
            evaluatee=self.bob,
            general_feedback="First evaluation"
        )
        with self.assertRaises(IntegrityError):
            PeerEvaluation.objects.create(
                team=self.team,
                evaluator=self.alice,
                evaluatee=self.bob,
                general_feedback="Duplicate evaluation"
            )

    def test_unique_together_evaluation_criterion_enforced(self):
        """Database enforces unique_together on ('evaluation', 'criterion')."""
        eval_record = PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.alice,
            evaluatee=self.bob
        )
        PeerEvaluationScore.objects.create(
            evaluation=eval_record,
            criterion=self.crit_tech,
            score=4
        )
        with self.assertRaises(IntegrityError):
            PeerEvaluationScore.objects.create(
                evaluation=eval_record,
                criterion=self.crit_tech,
                score=5
            )

    def test_evaluation_str_representation_does_not_reveal_evaluator(self):
        """Model __str__ returns team and evaluatee, preserving anonymity in default strings."""
        eval_record = PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.alice,
            evaluatee=self.bob
        )
        str_val = str(eval_record)
        self.assertEqual(str_val, f"Evaluation in {self.team.team_name} (To: {self.bob.name})")
        self.assertNotIn(self.alice.name, str_val)

    def test_cascade_delete_behavior(self):
        """Deleting team or evaluatee cascades cleanly to evaluation and scores."""
        eval_record = PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.alice,
            evaluatee=self.bob
        )
        PeerEvaluationScore.objects.create(
            evaluation=eval_record,
            criterion=self.crit_tech,
            score=5
        )
        self.assertEqual(PeerEvaluationScore.objects.count(), 1)
        eval_record.delete()
        self.assertEqual(PeerEvaluationScore.objects.count(), 0)


# =====================================================================
# 2. EVALUATION SUBMISSION & VALIDATION WORKFLOW TESTS
# =====================================================================
class PeerEvaluationSubmissionWorkflowTests(PeerEvaluationBaseTestCase):
    """Tests for evaluate_teammate view logic, form processing, and validation."""

    def test_successful_evaluation_submission_and_storage(self):
        """Valid submission creates PeerEvaluation and PeerEvaluationScore records."""
        self.client.force_login(self.alice)
        post_data = {
            f'criterion_{self.crit_tech.pk}': '5',
            f'criterion_{self.crit_collab.pk}': '4',
            'general_feedback': 'Great teammate, communicated effectively and met all deadlines.'
        }
        resp = self.client.post(self.eval_url_bob, post_data)

        # Redirects to team progress
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, self.progress_url)

        # Verify DB records
        eval_qs = PeerEvaluation.objects.filter(team=self.team, evaluator=self.alice, evaluatee=self.bob)
        self.assertTrue(eval_qs.exists())
        evaluation = eval_qs.first()
        self.assertEqual(evaluation.general_feedback, 'Great teammate, communicated effectively and met all deadlines.')

        scores = {s.criterion_id: s.score for s in evaluation.scores.all()}
        self.assertEqual(scores[self.crit_tech.pk], 5)
        self.assertEqual(scores[self.crit_collab.pk], 4)

    def test_submission_queues_success_flash_message(self):
        """Successful submission queues anonymous confirmation flash message."""
        self.client.force_login(self.alice)
        post_data = {
            f'criterion_{self.crit_tech.pk}': '5',
            f'criterion_{self.crit_collab.pk}': '5',
            'general_feedback': 'Perfect work.'
        }
        resp = self.client.post(self.eval_url_bob, post_data, follow=True)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        expected = f"Anonymous evaluation for {self.bob.name} submitted successfully."
        self.assertIn(expected, messages)

    def test_submission_without_optional_feedback_succeeds(self):
        """Submitting with blank general feedback succeeds and stores empty string."""
        self.client.force_login(self.alice)
        post_data = {
            f'criterion_{self.crit_tech.pk}': '4',
            f'criterion_{self.crit_collab.pk}': '4',
            'general_feedback': ''
        }
        resp = self.client.post(self.eval_url_bob, post_data)
        self.assertEqual(resp.status_code, 302)

        eval_obj = PeerEvaluation.objects.get(team=self.team, evaluator=self.alice, evaluatee=self.bob)
        self.assertEqual(eval_obj.general_feedback, '')

    def test_missing_criterion_score_fails_validation_and_rolls_back(self):
        """Omitting a score for any criterion rejects submission with error and saves nothing."""
        self.client.force_login(self.alice)
        post_data = {
            f'criterion_{self.crit_tech.pk}': '5',
            # crit_collab omitted
            'general_feedback': 'Missing score test'
        }
        resp = self.client.post(self.eval_url_bob, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        # No records created
        self.assertFalse(PeerEvaluation.objects.filter(team=self.team, evaluator=self.alice).exists())
        self.assertEqual(PeerEvaluationScore.objects.count(), 0)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any("You must provide a score for: Collaboration & Communication" in m for m in messages))

    def test_cannot_evaluate_oneself(self):
        """Student attempting to evaluate themselves is rejected with error."""
        self.client.force_login(self.alice)
        self_url = f"/academic/student/team/{self.team.team_id}/evaluate/{self.alice.pk}/"
        resp = self.client.get(self_url, follow=True)

        self.assertEqual(resp.status_code, 200)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("You cannot evaluate yourself.", messages)
        self.assertFalse(PeerEvaluation.objects.filter(team=self.team, evaluator=self.alice).exists())

    def test_duplicate_evaluation_submission_blocked(self):
        """Submitting a second evaluation for the same teammate is blocked with error."""
        # Initial evaluation
        PeerEvaluation.objects.create(team=self.team, evaluator=self.alice, evaluatee=self.bob)

        self.client.force_login(self.alice)
        post_data = {
            f'criterion_{self.crit_tech.pk}': '4',
            f'criterion_{self.crit_collab.pk}': '4',
        }
        resp = self.client.post(self.eval_url_bob, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any(f"You have already submitted an evaluation for {self.bob.name}." in m for m in messages))
        self.assertEqual(PeerEvaluation.objects.filter(team=self.team, evaluator=self.alice, evaluatee=self.bob).count(), 1)

    def test_evaluation_blocked_when_project_deadline_passed(self):
        """When project deadline has expired, evaluation access and submission are blocked."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=2)
        )
        self.client.force_login(self.alice)
        resp = self.client.get(self.eval_url_bob, follow=True)

        self.assertEqual(resp.status_code, 200)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Peer evaluations are locked. The deadline has passed.", messages)

    def test_evaluation_blocked_when_no_criteria_configured(self):
        """If project has no evaluation criteria, access warns and redirects."""
        EvaluationCriterion.objects.filter(project=self.project).delete()

        self.client.force_login(self.alice)
        resp = self.client.get(self.eval_url_bob, follow=True)

        self.assertEqual(resp.status_code, 200)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Your instructor has not configured evaluation criteria for this project yet.", messages)

    def test_cannot_evaluate_non_teammate_returns_404(self):
        """Attempting to evaluate a user who is not a member of the team returns 404."""
        self.client.force_login(self.alice)
        outsider_url = f"/academic/student/team/{self.team.team_id}/evaluate/{self.outsider.pk}/"
        resp = self.client.get(outsider_url)
        self.assertEqual(resp.status_code, 404)

    def test_cannot_evaluate_in_unauthorized_team_returns_404(self):
        """Student cannot evaluate users in a team they do not belong to."""
        other_team = Team.objects.create(project=self.project, team_name="Other Squad")
        TeamMember.objects.create(team=other_team, user=self.outsider)

        self.client.force_login(self.alice)
        bad_url = f"/academic/student/team/{other_team.team_id}/evaluate/{self.outsider.pk}/"
        resp = self.client.get(bad_url)
        self.assertEqual(resp.status_code, 404)

    def test_unauthenticated_user_redirected_to_login(self):
        """Unauthenticated requests are redirected to login."""
        resp = self.client.get(self.eval_url_bob)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.url)

    def test_non_student_role_denied(self):
        """Instructor attempting to access student evaluate view receives 403."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.eval_url_bob)
        self.assertEqual(resp.status_code, 403)


# =====================================================================
# 3. ANONYMITY & DATA PRIVACY VERIFICATION TESTS
# =====================================================================
class PeerEvaluationAnonymityAndPrivacyTests(PeerEvaluationBaseTestCase):
    """
    Acceptance Criteria Validation:
    Evaluator identity is strictly confidential and never exposed to other students.
    """

    def setUp(self):
        super().setUp()
        # Alice evaluates Bob
        self.eval_alice_to_bob = PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.alice,
            evaluatee=self.bob,
            general_feedback="Confidential Alice feedback regarding Bob's code."
        )
        PeerEvaluationScore.objects.create(
            evaluation=self.eval_alice_to_bob,
            criterion=self.crit_tech,
            score=5
        )
        PeerEvaluationScore.objects.create(
            evaluation=self.eval_alice_to_bob,
            criterion=self.crit_collab,
            score=4
        )

    def test_evaluatee_cannot_see_evaluator_identity_on_team_progress(self):
        """Bob visits team progress and CANNOT see that Alice evaluated him or what scores she gave."""
        self.client.force_login(self.bob)
        resp = self.client.get(self.progress_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        # Bob's page must NOT contain Alice's evaluation, feedback, or score details
        self.assertNotIn("Confidential Alice feedback", content)
        self.assertNotIn("Alice Evaluator evaluated you", content)
        # Evaluated IDs for Bob should be empty (Bob hasn't evaluated anyone yet)
        self.assertEqual(list(resp.context['evaluated_ids']), [])

    def test_third_party_teammate_cannot_see_evaluator_identity(self):
        """Charlie visits team progress and CANNOT see that Alice evaluated Bob."""
        self.client.force_login(self.charlie)
        resp = self.client.get(self.progress_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertNotIn("Confidential Alice feedback", content)
        self.assertEqual(list(resp.context['evaluated_ids']), [])
        # Charlie still sees 'Evaluate Peer' for Bob because Charlie hasn't evaluated Bob
        self.assertIn(f"/academic/student/team/{self.team.team_id}/evaluate/{self.bob.pk}/", content)

    def test_evaluated_ids_context_isolated_strictly_to_logged_in_user(self):
        """Context 'evaluated_ids' is scoped to request.user and does not leak other peers' activities."""
        # Alice evaluated Bob
        self.client.force_login(self.alice)
        resp_alice = self.client.get(self.progress_url)
        self.assertIn(self.bob.pk, resp_alice.context['evaluated_ids'])
        self.assertNotIn(self.charlie.pk, resp_alice.context['evaluated_ids'])

        # Bob logs in: Bob has evaluated no one
        self.client.force_login(self.bob)
        resp_bob = self.client.get(self.progress_url)
        self.assertNotIn(self.bob.pk, resp_bob.context['evaluated_ids'])
        self.assertNotIn(self.alice.pk, resp_bob.context['evaluated_ids'])

    def test_evaluate_teammate_form_header_displays_confidentiality_notice(self):
        """Evaluate page explicitly documents confidentiality to the student evaluator."""
        self.client.force_login(self.alice)
        resp = self.client.get(self.eval_url_charlie)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertIn("Anonymous Peer Evaluation", content)
        self.assertIn("Your identity will be kept strictly confidential from the student being evaluated.", content)

    def test_student_dashboard_does_not_leak_peer_evaluations_or_identities(self):
        """Student dashboard context and markup do not expose peer evaluations or evaluators."""
        self.client.force_login(self.bob)
        resp = self.client.get("/academic/student/")
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertNotIn("Confidential Alice feedback", content)
        self.assertNotIn("evaluator", resp.context)


# =====================================================================
# 4. UI BADGE & BUTTON TRANSITIONS TESTS
# =====================================================================
class PeerEvaluationUITransitionsTests(PeerEvaluationBaseTestCase):
    """Tests verify UI rendering of Evaluate Peer buttons and Evaluated badges on team progress."""

    def test_team_progress_initially_renders_evaluate_peer_button(self):
        """Before evaluation, teammate row renders 'Evaluate Peer' button."""
        self.client.force_login(self.alice)
        resp = self.client.get(self.progress_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertIn("Evaluate Peer", content)
        self.assertIn(self.eval_url_bob, content)
        self.assertIn(self.eval_url_charlie, content)

    def test_team_progress_renders_evaluated_badge_after_submission(self):
        """After submitting evaluation for Bob, Alice sees green 'Evaluated' badge for Bob."""
        PeerEvaluation.objects.create(
            team=self.team,
            evaluator=self.alice,
            evaluatee=self.bob
        )

        self.client.force_login(self.alice)
        resp = self.client.get(self.progress_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertIn("Evaluated", content)
        self.assertIn("fa-check-circle", content)
        # Bob's link is gone, but Charlie's evaluate link remains
        self.assertNotIn(self.eval_url_bob, content)
        self.assertIn(self.eval_url_charlie, content)

    def test_self_row_renders_you_badge_without_evaluation_button(self):
        """Logged-in student's own row displays 'You' badge and no evaluate button."""
        self.client.force_login(self.alice)
        resp = self.client.get(self.progress_url)

        content = resp.content.decode('utf-8')
        self.assertIn(">You</span>", content)
        self_url = f"/academic/student/team/{self.team.team_id}/evaluate/{self.alice.pk}/"
        self.assertNotIn(self_url, content)

    def test_closed_badge_rendered_when_project_deadline_passed(self):
        """When deadline has passed, unevaluated teammates render 'Closed' badge."""
        Project.objects.filter(pk=self.project.pk).update(
            deadline=timezone.now() - timedelta(hours=1)
        )
        self.client.force_login(self.alice)
        resp = self.client.get(self.progress_url)

        content = resp.content.decode('utf-8')
        self.assertIn("Closed", content)
        self.assertIn("fa-lock", content)
        self.assertNotIn("Evaluate Peer", content)


# =====================================================================
# 5. LIVE SELENIUM BROWSER E2E TESTS (HEADLESS CHROME)
# =====================================================================
class PeerEvaluationSeleniumE2ETests(StaticLiveServerTestCase):
    """End-to-end browser test verifying evaluation submission and confidentiality."""

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
            email="coord_pe_e2e@test.com",
            name="Coord E2E",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_pe_e2e@test.com",
            name="Inst E2E",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.alice = User.objects.create_user(
            email="alice_pe_e2e@test.com",
            name="Alice Evaluator",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.bob = User.objects.create_user(
            email="bob_pe_e2e@test.com",
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
            title="E2E Peer System",
            description="Testing anonymous evaluations",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Pioneer Squad",
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

        self.crit1 = EvaluationCriterion.objects.create(
            project=self.project,
            name="Code Quality",
            description="Clean code and architecture",
            max_score=5
        )
        self.crit2 = EvaluationCriterion.objects.create(
            project=self.project,
            name="Punctuality",
            description="On time meeting attendance",
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

    def _logout(self):
        try:
            logout_btn = self.driver.find_element(By.XPATH, "//form[contains(@action, '/logout')]//button")
            logout_btn.click()
            self.wait.until(lambda d: "/login" in d.current_url or "/dashboard" not in d.current_url)
        except Exception:
            self.driver.get(f"{self.live_server_url}/accounts/logout/")

    def test_e2e_anonymous_peer_evaluation_submission_and_confidentiality(self):
        """E2E workflow:
        1. Alice logs in -> visits team progress -> sees 'Evaluate Peer' next to Bob.
        2. Alice clicks 'Evaluate Peer' -> fills scores and feedback -> submits.
        3. Alice redirected to team progress with success message -> sees 'Evaluated' badge next to Bob.
        4. Alice logs out -> Bob logs in -> visits team progress.
        5. Verifies Bob cannot see who evaluated him, cannot see Alice's feedback or scores.
        """
        progress_url = f"{self.live_server_url}/academic/student/team/{self.team.team_id}/progress/"

        # 1. Login as Alice
        self._login("alice_pe_e2e@test.com", "password123")
        self.driver.get(progress_url)

        # 2. Click 'Evaluate Peer' for Bob
        eval_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Evaluate Peer')]")))
        eval_btn.click()

        # 3. Confirm on evaluate page and check confidentiality text
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(text(), 'Anonymous Peer Evaluation')]")))
        eval_page_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Your identity will be kept strictly confidential from the student being evaluated.", eval_page_text)

        # Select scores for criteria
        select1 = Select(self.driver.find_element(By.NAME, f"criterion_{self.crit1.pk}"))
        select1.select_by_value("5")

        select2 = Select(self.driver.find_element(By.NAME, f"criterion_{self.crit2.pk}"))
        select2.select_by_value("4")

        feedback_input = self.driver.find_element(By.NAME, "general_feedback")
        feedback_input.send_keys("Superb initiative on CI/CD pipelines.")

        # Submit form
        submit_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Submit Anonymous Evaluation')]")
        submit_btn.click()

        # 4. Verified on progress page with success message
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'submitted successfully')]")))
        alice_progress_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Evaluated", alice_progress_text)
        self.assertNotIn("Evaluate Peer", alice_progress_text)

        # 5. Logout Alice, Login Bob
        self._logout()
        self._login("bob_pe_e2e@test.com", "password123")
        self.driver.get(progress_url)

        # 6. Verify confidentiality on Bob's view
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(., 'Team Progress')]")))
        bob_progress_text = self.driver.find_element(By.TAG_NAME, "body").text

        # Bob CANNOT see Alice's feedback or scores
        self.assertNotIn("Superb initiative on CI/CD pipelines.", bob_progress_text)
        self.assertNotIn("Alice Evaluator evaluated you", bob_progress_text)
        # Bob sees 'Evaluate Peer' next to Alice
        self.assertIn("Evaluate Peer", bob_progress_text)

