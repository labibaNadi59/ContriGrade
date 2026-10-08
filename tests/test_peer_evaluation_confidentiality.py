
import os
import sys
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, Client
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone
from django.contrib.messages import get_messages
from django.urls import reverse

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
# 1. SHARED BASE FIXTURE
# =====================================================================
class PeerEvaluationConfidentialityBaseTestCase(TestCase):
    """Common test fixture for confidentiality and authorized access to peer evaluations."""

    def setUp(self):
        super().setUp()
        self.coordinator = User.objects.create_user(
            email="coord_conf@test.com",
            name="Coordinator Vance",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_conf@test.com",
            name="Dr. Aris Reed",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.admin = User.objects.create_user(
            email="admin_conf@test.com",
            name="System Admin",
            role=User.Role.ADMIN,
            password="password123"
        )
        self.alice = User.objects.create_user(
            email="alice_conf@test.com",
            name="Alice Evaluator",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.bob = User.objects.create_user(
            email="bob_conf@test.com",
            name="Bob Evaluatee",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.charlie = User.objects.create_user(
            email="charlie_conf@test.com",
            name="Charlie Teammate",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.diana = User.objects.create_user(
            email="diana_conf@test.com",
            name="Diana Outsider",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE410",
            course_name="Distributed Systems",
            coordinator=self.coordinator
        )
        self.section1 = CourseSection.objects.create(
            course=self.course,
            section_name="Section 1",
            instructor=self.instructor
        )
        self.section2 = CourseSection.objects.create(
            course=self.course,
            section_name="Section 2",
            instructor=self.instructor
        )
        self.section1.students.add(self.alice, self.bob, self.charlie)
        self.section2.students.add(self.diana)

        self.project = Project.objects.create(
            section=self.section1,
            title="Consensus Engine",
            description="Raft-based key-value store",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Alpha Squad",
            github_repo_url="https://github.com/contrigrade/alpha-repo"
        )
        TeamMember.objects.create(team=self.team, user=self.alice)
        TeamMember.objects.create(team=self.team, user=self.bob)
        TeamMember.objects.create(team=self.team, user=self.charlie)

        self.project2 = Project.objects.create(
            section=self.section2,
            title="Paxos Cluster",
            description="Replicated state machine",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team2 = Team.objects.create(
            project=self.project2,
            team_name="Beta Squad",
            github_repo_url="https://github.com/contrigrade/beta-repo"
        )
        TeamMember.objects.create(team=self.team2, user=self.diana)

        self.crit1 = EvaluationCriterion.objects.create(
            project=self.project,
            name="Technical Depth",
            description="Code quality and systems rigor",
            max_score=5
        )
        self.crit2 = EvaluationCriterion.objects.create(
            project=self.project,
            name="Collaboration",
            description="Team communication and punctuality",
            max_score=5
        )

        self.commits_patcher = patch('academic.views.fetch_team_commits')
        self.mock_fetch = self.commits_patcher.start()
        self.mock_fetch.return_value = {
            'status': 'success',
            'total_commits': 0,
            'total_branches': 1,
            'commits': []
        }
        self.addCleanup(self.commits_patcher.stop)

        self.inst_eval_url = reverse('team_peer_evaluations', kwargs={'team_id': self.team.pk})
        self.student_progress_url = reverse('student_team_progress', kwargs={'team_id': self.team.pk})
        self.eval_bob_url = reverse('evaluate_teammate', kwargs={'team_id': self.team.pk, 'teammate_id': self.bob.pk})
        self.eval_charlie_url = reverse('evaluate_teammate', kwargs={'team_id': self.team.pk, 'teammate_id': self.charlie.pk})
        self.student_dash_url = reverse('student_dashboard')
        self.reports_hub_url = reverse('reports_hub')

        self.secret_feedback_alice = "Confidential from Alice: Bob struggled with RPC unit tests."
        self.secret_feedback_charlie = "Confidential from Charlie: Bob completed heartbeat implementation on time."

    def create_evaluation(self, evaluator, evaluatee, score1, score2, feedback=""):
        """Helper to create a completed peer evaluation with scores."""
        evaluation = PeerEvaluation.objects.create(
            team=self.team,
            evaluator=evaluator,
            evaluatee=evaluatee,
            general_feedback=feedback
        )
        PeerEvaluationScore.objects.create(evaluation=evaluation, criterion=self.crit1, score=score1)
        PeerEvaluationScore.objects.create(evaluation=evaluation, criterion=self.crit2, score=score2)
        return evaluation


# =====================================================================
# 2. UNAUTHORIZED ROLE ACCESS CONTROL TESTS
# =====================================================================
class PeerEvaluationAccessControlTests(PeerEvaluationConfidentialityBaseTestCase):
    """Verifies that unauthorized users cannot access confidential peer evaluation reports."""

    def test_unauthenticated_user_redirected_from_peer_evaluations(self):
        """Unauthenticated visitor cannot access instructor peer evaluations report."""
        resp = self.client.get(self.inst_eval_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.headers['Location'])
        self.assertIn(f'next={self.inst_eval_url}', resp.headers['Location'])

    def test_evaluatee_student_blocked_from_team_peer_evaluations(self):
        """Evaluatee (Bob) cannot view aggregated peer evaluation responses targeting him."""
        self.create_evaluation(self.alice, self.bob, 4, 3, self.secret_feedback_alice)
        self.client.force_login(self.bob)

        resp = self.client.get(self.inst_eval_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Access denied. Instructor privileges required.", messages)
        content = resp.content.decode('utf-8')
        self.assertIn("Student Dashboard", content)
        self.assertNotIn("Aggregated Peer Scores", content)
        self.assertNotIn(self.secret_feedback_alice, content)

    def test_evaluator_student_blocked_from_team_peer_evaluations(self):
        """Evaluator (Alice) cannot access the instructor peer evaluations report."""
        self.create_evaluation(self.alice, self.bob, 5, 4, self.secret_feedback_alice)
        self.client.force_login(self.alice)

        resp = self.client.get(self.inst_eval_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Access denied. Instructor privileges required.", messages)
        self.assertNotIn("Aggregated Peer Scores", resp.content.decode('utf-8'))

    def test_teammate_student_blocked_from_team_peer_evaluations(self):
        """Third-party teammate (Charlie) cannot access team peer evaluations report."""
        self.create_evaluation(self.alice, self.bob, 4, 5, self.secret_feedback_alice)
        self.client.force_login(self.charlie)

        resp = self.client.get(self.inst_eval_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Access denied. Instructor privileges required.", messages)
        self.assertNotIn("Aggregated Peer Scores", resp.content.decode('utf-8'))

    def test_outsider_student_blocked_from_team_peer_evaluations(self):
        """Outsider student (Diana) cannot access team peer evaluations report."""
        self.client.force_login(self.diana)

        resp = self.client.get(self.inst_eval_url, follow=True)
        self.assertEqual(resp.status_code, 200)

        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Access denied. Instructor privileges required.", messages)
        self.assertNotIn("Aggregated Peer Scores", resp.content.decode('utf-8'))

    def test_student_post_request_to_team_peer_evaluations_blocked(self):
        """Direct POST request by student to peer evaluations report is rejected."""
        self.client.force_login(self.bob)
        resp = self.client.post(self.inst_eval_url, {'tamper': 'true'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        messages = [m.message for m in get_messages(resp.wsgi_request)]
        self.assertIn("Access denied. Instructor privileges required.", messages)

    def test_unauthenticated_post_request_to_team_peer_evaluations_blocked(self):
        """Direct POST request by unauthenticated user is redirected to login."""
        resp = self.client.post(self.inst_eval_url, {'tamper': 'true'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.headers['Location'])


# =====================================================================
# 3. STUDENT VIEWS RESPONSE CONFIDENTIALITY TESTS
# =====================================================================
class StudentViewsResponseConfidentialityTests(PeerEvaluationConfidentialityBaseTestCase):
    """Verifies confidential evaluation responses, scores, and identities are never exposed in student views."""

    def test_evaluatee_cannot_see_peer_evaluation_scores_or_comments_in_team_progress(self):
        """Evaluatee visiting team progress cannot see peer evaluation feedback or scores received."""
        self.create_evaluation(self.alice, self.bob, 2, 3, self.secret_feedback_alice)

        self.client.force_login(self.bob)
        resp = self.client.get(self.student_progress_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertNotIn(self.secret_feedback_alice, content)
        self.assertNotIn("struggled with RPC unit tests", content)
        self.assertNotIn("Technical Depth", content)
        self.assertNotIn("Collaboration", content)
        self.assertNotIn("Alice Evaluator", [e for e in content if "evaluat" in e.lower()])

        evaluated_ids = list(resp.context.get('evaluated_ids', []))
        self.assertEqual(evaluated_ids, [])

    def test_evaluatee_cannot_see_peer_evaluation_in_student_dashboard(self):
        """Student dashboard does not leak peer evaluation feedback, scores, or evaluator identity."""
        self.create_evaluation(self.alice, self.bob, 5, 5, self.secret_feedback_alice)

        self.client.force_login(self.bob)
        resp = self.client.get(self.student_dash_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertNotIn(self.secret_feedback_alice, content)
        self.assertNotIn("evaluator", resp.context)
        self.assertNotIn("PeerEvaluation", str(resp.context))

    def test_other_teammates_cannot_see_peer_evaluations_given_or_received_by_peers(self):
        """Third-party teammate visiting progress cannot see evaluations given by or to other teammates."""
        self.create_evaluation(self.alice, self.bob, 4, 4, self.secret_feedback_alice)

        self.client.force_login(self.charlie)
        resp = self.client.get(self.student_progress_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertNotIn(self.secret_feedback_alice, content)
        self.assertEqual(list(resp.context.get('evaluated_ids', [])), [])

    def test_evaluated_ids_in_context_is_strictly_isolated_per_evaluator(self):
        """The evaluated_ids list in template context only contains users evaluated by the requesting student."""
        self.create_evaluation(self.alice, self.bob, 5, 5, self.secret_feedback_alice)
        self.create_evaluation(self.bob, self.charlie, 4, 4, "Bob feedback for Charlie")

        self.client.force_login(self.alice)
        resp_alice = self.client.get(self.student_progress_url)
        self.assertEqual(list(resp_alice.context['evaluated_ids']), [self.bob.pk])

        self.client.force_login(self.bob)
        resp_bob = self.client.get(self.student_progress_url)
        self.assertEqual(list(resp_bob.context['evaluated_ids']), [self.charlie.pk])

        self.client.force_login(self.charlie)
        resp_charlie = self.client.get(self.student_progress_url)
        self.assertEqual(list(resp_charlie.context['evaluated_ids']), [])

    def test_evaluate_teammate_form_does_not_reveal_existing_peer_responses(self):
        """Evaluating a teammate presents a blank form without revealing prior evaluations by other peers."""
        self.create_evaluation(self.alice, self.bob, 4, 4, self.secret_feedback_alice)

        self.client.force_login(self.charlie)
        resp = self.client.get(self.eval_bob_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertNotIn(self.secret_feedback_alice, content)
        self.assertIn("Anonymous Peer Evaluation", content)
        self.assertIn("Your identity will be kept strictly confidential from the student being evaluated.", content)


# =====================================================================
# 4. EVALUATION FORM ACCESS CONTROL & BOUNDARY TESTS
# =====================================================================
class EvaluationFormAccessControlTests(PeerEvaluationConfidentialityBaseTestCase):
    """Verifies unauthorized students and staff cannot access or tamper with evaluation forms."""

    def test_unauthenticated_user_cannot_access_evaluate_teammate_form(self):
        """Unauthenticated user is redirected to login when attempting to access evaluation form."""
        resp = self.client.get(self.eval_bob_url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login/', resp.headers['Location'])

    def test_outsider_student_cannot_access_evaluate_teammate_form(self):
        """Student from another team/section cannot access evaluation form for an external team."""
        self.client.force_login(self.diana)
        resp = self.client.get(self.eval_bob_url)
        self.assertEqual(resp.status_code, 404)

    def test_student_cannot_evaluate_non_teammate_via_url_tampering(self):
        """Student cannot evaluate an outsider student not belonging to their team."""
        self.client.force_login(self.alice)
        tampered_url = reverse('evaluate_teammate', kwargs={'team_id': self.team.pk, 'teammate_id': self.diana.pk})
        resp = self.client.get(tampered_url)
        self.assertEqual(resp.status_code, 404)

    def test_instructor_cannot_access_student_evaluate_teammate_form(self):
        """Instructor cannot access peer evaluation submission form (restricted to students)."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.eval_bob_url)
        self.assertIn(resp.status_code, [302, 403])

    def test_coordinator_cannot_access_student_evaluate_teammate_form(self):
        """Coordinator cannot access peer evaluation submission form (restricted to students)."""
        self.client.force_login(self.coordinator)
        resp = self.client.get(self.eval_bob_url)
        self.assertIn(resp.status_code, [302, 403])


# =====================================================================
# 5. AUTHORIZED STAFF ACCESS & ANONYMITY PRESERVATION TESTS
# =====================================================================
class AuthorizedStaffAccessAndAnonymityTests(PeerEvaluationConfidentialityBaseTestCase):
    """Verifies authorized staff can access reports while student evaluator anonymity is preserved."""

    def setUp(self):
        super().setUp()
        self.create_evaluation(self.alice, self.bob, 4, 2, self.secret_feedback_alice)
        self.create_evaluation(self.charlie, self.bob, 5, 4, self.secret_feedback_charlie)

    def test_instructor_can_access_team_peer_evaluations_report(self):
        """Instructor can view aggregated peer evaluation responses for their team."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.inst_eval_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertIn("Aggregated Peer Scores", content)
        self.assertIn("Confidentiality Enforced", content)
        self.assertIn(self.secret_feedback_alice, content)
        self.assertIn(self.secret_feedback_charlie, content)

    def test_evaluator_identities_are_strictly_scrubbed_from_instructor_view(self):
        """Instructor view anonymizes feedback and does not attribute comments to evaluators."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.inst_eval_url)
        self.assertEqual(resp.status_code, 200)

        assessment_data = resp.context['assessment_data']
        bob_assessment = next(d for d in assessment_data if d['student'] == self.bob)

        self.assertIn(self.secret_feedback_alice, bob_assessment['feedback_list'])
        self.assertIn(self.secret_feedback_charlie, bob_assessment['feedback_list'])

        self.assertNotIn('evaluator', bob_assessment)
        self.assertNotIn('evaluators', bob_assessment)
        self.assertNotIn('evaluator_ids', bob_assessment)

        content = resp.content.decode('utf-8')
        self.assertNotIn("Alice Evaluator: " + self.secret_feedback_alice, content)
        self.assertNotIn("Charlie Teammate: " + self.secret_feedback_charlie, content)

    def test_scores_are_mathematically_aggregated_obscuring_individual_ratings(self):
        """Scores are averaged per criterion; individual evaluator score submissions are not revealed."""
        self.client.force_login(self.instructor)
        resp = self.client.get(self.inst_eval_url)
        self.assertEqual(resp.status_code, 200)

        assessment_data = resp.context['assessment_data']
        bob_assessment = next(d for d in assessment_data if d['student'] == self.bob)

        crit1_breakdown = next(b for b in bob_assessment['scores_breakdown'] if b['criterion_name'] == self.crit1.name)
        crit2_breakdown = next(b for b in bob_assessment['scores_breakdown'] if b['criterion_name'] == self.crit2.name)

        # Alice gave 4, Charlie gave 5 -> Average is 4.5
        self.assertEqual(crit1_breakdown['avg_score'], 4.5)
        # Alice gave 2, Charlie gave 4 -> Average is 3.0
        self.assertEqual(crit2_breakdown['avg_score'], 3.0)

    def test_coordinator_can_access_with_anonymity_preserved(self):
        """Coordinator has authorized access to peer evaluation report with anonymity enforced."""
        self.client.force_login(self.coordinator)
        resp = self.client.get(self.inst_eval_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertIn("Aggregated Peer Scores", content)
        self.assertIn("Confidentiality Enforced", content)
        self.assertIn(self.secret_feedback_alice, content)

    def test_admin_can_access_with_anonymity_preserved(self):
        """Administrator has authorized access to peer evaluation report with anonymity enforced."""
        self.client.force_login(self.admin)
        resp = self.client.get(self.inst_eval_url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        self.assertIn("Aggregated Peer Scores", content)
        self.assertIn("Confidentiality Enforced", content)
        self.assertIn(self.secret_feedback_alice, content)

    def test_reports_hub_access_control(self):
        """Unauthorized students cannot access reports hub; authorized instructors can."""
        self.client.force_login(self.bob)
        resp_student = self.client.get(self.reports_hub_url)
        self.assertEqual(resp_student.status_code, 302)

        resp_anon = self.client.get(self.reports_hub_url)
        self.assertEqual(resp_anon.status_code, 302)

        self.client.force_login(self.instructor)
        resp_inst = self.client.get(self.reports_hub_url)
        self.assertEqual(resp_inst.status_code, 200)


# =====================================================================
# 6. LIVE SELENIUM BROWSER E2E TESTS (HEADLESS CHROME)
# =====================================================================
class PeerEvaluationConfidentialitySeleniumTests(StaticLiveServerTestCase):
    """End-to-end browser test verifying peer evaluation confidentiality and authorized access."""

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
            email="coord_se_conf@test.com",
            name="Coord Confidential",
            role=User.Role.COORDINATOR,
            password="password123"
        )
        self.instructor = User.objects.create_user(
            email="inst_se_conf@test.com",
            name="Dr. Aris Thorne",
            role=User.Role.INSTRUCTOR,
            password="password123"
        )
        self.alice = User.objects.create_user(
            email="alice_se_conf@test.com",
            name="Alice Confidential",
            role=User.Role.STUDENT,
            password="password123"
        )
        self.bob = User.objects.create_user(
            email="bob_se_conf@test.com",
            name="Bob Confidential",
            role=User.Role.STUDENT,
            password="password123"
        )

        self.course = Course.objects.create(
            course_code="CSE410",
            course_name="Distributed Systems",
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
            title="Confidential Evaluation Project",
            description="Testing live response confidentiality",
            deadline=timezone.now() + timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Security Squad",
            github_repo_url="https://github.com/contrigrade/sec-repo"
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
            name="Architecture & Design",
            description="Software architecture standard",
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

    def test_e2e_peer_evaluation_confidentiality_and_authorized_access(self):
        """Live browser workflow:
        1. Alice logs in and submits a confidential peer evaluation for Bob with secret feedback.
        2. Alice logs out.
        3. Bob (evaluatee) logs in:
           - Views Team Progress: verifies confidential feedback and scores are NOT present.
           - Views Student Dashboard: verifies confidential feedback is NOT present.
           - Manually navigates to instructor evaluations report URL: blocked with Access Denied.
        4. Bob logs out.
        5. Instructor logs in:
           - Navigates to instructor evaluations report URL: access granted (Aggregated Peer Scores).
           - Confirms confidential feedback is visible for Bob.
           - Confirms Alice's identity is scrubbed and not associated with the feedback.
        """
        progress_url = f"{self.live_server_url}/academic/student/team/{self.team.team_id}/progress/"
        eval_bob_url = f"{self.live_server_url}/academic/student/team/{self.team.team_id}/evaluate/{self.bob.pk}/"
        inst_eval_url = f"{self.live_server_url}/academic/instructor/team/{self.team.team_id}/evaluations/"
        secret_comment = "SECRET_CONFIDENTIAL_REMARK_741: Bob needs to improve unit test coverage."

        # Step 1: Alice logs in and evaluates Bob
        self._login("alice_se_conf@test.com", "password123")
        self.driver.get(eval_bob_url)

        self.wait.until(EC.presence_of_element_located((By.NAME, f"criterion_{self.crit.pk}")))
        score_select = Select(self.driver.find_element(By.NAME, f"criterion_{self.crit.pk}"))
        score_select.select_by_value("4")

        feedback_input = self.driver.find_element(By.NAME, "general_feedback")
        feedback_input.send_keys(secret_comment)

        submit_btn = self.driver.find_element(By.XPATH, "//button[contains(., 'Submit Anonymous Evaluation')]")
        submit_btn.click()

        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'submitted successfully')]")))

        # Step 2: Alice logs out
        self.driver.delete_all_cookies()

        # Step 3: Bob (evaluatee) logs in and verifies confidentiality
        self._login("bob_se_conf@test.com", "password123")
        self.driver.get(progress_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(., 'Team Progress')]")))

        page_source_bob_progress = self.driver.page_source
        self.assertNotIn("SECRET_CONFIDENTIAL_REMARK_741", page_source_bob_progress)
        self.assertNotIn("unit test coverage", page_source_bob_progress)

        # Bob checks dashboard
        self.driver.get(f"{self.live_server_url}/academic/student/")
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(., 'Assessment Hub') or contains(., 'Student Dashboard')]")))
        page_source_bob_dash = self.driver.page_source
        self.assertNotIn("SECRET_CONFIDENTIAL_REMARK_741", page_source_bob_dash)

        # Bob attempts direct access to instructor evaluation report
        self.driver.get(inst_eval_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Access denied. Instructor privileges required.')]")))
        self.assertNotIn("/evaluations/", self.driver.current_url)

        # Step 4: Bob logs out
        self.driver.delete_all_cookies()

        # Step 5: Instructor logs in and accesses authorized report
        self._login("inst_se_conf@test.com", "password123")
        self.driver.get(inst_eval_url)
        self.wait.until(EC.presence_of_element_located((By.XPATH, "//h2[contains(., 'Aggregated Peer Scores')]")))

        report_page_text = self.driver.find_element(By.TAG_NAME, "body").text
        self.assertIn("Confidentiality Enforced", report_page_text)
        self.assertIn("SECRET_CONFIDENTIAL_REMARK_741: Bob needs to improve unit test coverage.", report_page_text)

        # Evaluator anonymity check: Alice's name must NOT be attached to the feedback
        self.assertNotIn("Alice Confidential: SECRET_CONFIDENTIAL_REMARK_741", report_page_text)

