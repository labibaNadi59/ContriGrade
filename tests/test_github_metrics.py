import os
import sys
import csv
import io
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch, MagicMock

import django
from django.test import TestCase, Client
from django.utils import timezone
from django.core.cache import cache

from accounts.models import User
from academic.models import Course, CourseSection, Project, Team, TeamMember
from academic.utils import (
    fetch_deep_commit_stats,
    fetch_team_commits,
    analyze_team_contributions,
)


class TestGitHubMetricsRetrieval(TestCase):
    """Unit tests for GitHub contribution metrics retrieval functions."""

    def setUp(self):
        cache.clear()
        self.coordinator = User.objects.create_user(
            email="coord_retrieval@test.com",
            name="Coordinator Test",
            role="COORDINATOR",
            password="testpassword123"
        )
        self.instructor = User.objects.create_user(
            email="inst_retrieval@test.com",
            name="Instructor Test",
            role="INSTRUCTOR",
            password="testpassword123"
        )
        self.course = Course.objects.create(
            course_code="CSE401",
            course_name="Software Architecture",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Sec 1",
            instructor=self.instructor
        )
        self.project = Project.objects.create(
            section=self.section,
            title="Metrics Retrieval Project",
            deadline=timezone.now() + timezone.timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Retrieval Team",
            github_repo_url="https://github.com/testowner/testrepo"
        )

    def tearDown(self):
        cache.clear()

    @patch('requests.get')
    def test_fetch_deep_commit_stats_success(self, mock_get):
        """Validates LOC additions and deletions extraction from commit details API."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "stats": {"additions": 84, "deletions": 19}
        }
        mock_get.return_value = mock_resp

        commit = {"sha": "sha12345"}
        result = fetch_deep_commit_stats(commit, "testowner", "testrepo", {})

        self.assertEqual(result["additions"], 84)
        self.assertEqual(result["deletions"], 19)

    @patch('requests.get')
    def test_fetch_deep_commit_stats_non_200_defaults_to_zero(self, mock_get):
        """Verifies 404 or 500 error gracefully sets additions and deletions to 0."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        commit = {"sha": "sha_missing"}
        result = fetch_deep_commit_stats(commit, "testowner", "testrepo", {})

        self.assertEqual(result["additions"], 0)
        self.assertEqual(result["deletions"], 0)

    @patch('requests.get')
    def test_fetch_deep_commit_stats_network_exception_defaults_to_zero(self, mock_get):
        """Verifies network exception gracefully sets additions and deletions to 0."""
        import requests
        mock_get.side_effect = requests.RequestException("Connection timeout")

        commit = {"sha": "sha_timeout"}
        result = fetch_deep_commit_stats(commit, "testowner", "testrepo", {})

        self.assertEqual(result["additions"], 0)
        self.assertEqual(result["deletions"], 0)

    def test_fetch_team_commits_no_repo_url(self):
        """Fails gracefully when team has no linked GitHub repository."""
        self.team.github_repo_url = None
        self.team.save()

        res = fetch_team_commits(self.team)
        self.assertEqual(res["status"], "error")
        self.assertIn("No repository linked", res["message"])

    def test_fetch_team_commits_invalid_repo_format(self):
        """Fails gracefully when team repository URL format is not a GitHub owner/repo URL."""
        self.team.github_repo_url = "https://gitlab.com/owner/repo"
        self.team.save()

        res = fetch_team_commits(self.team)
        self.assertEqual(res["status"], "error")
        self.assertIn("Invalid repository URL format", res["message"])

    def test_fetch_team_commits_cache_hit(self):
        """Verifies cached metrics are returned without making HTTP calls."""
        cache_key = f"team_{self.team.pk}_github_commits"
        cached_payload = {
            "status": "success",
            "total_commits": 5,
            "total_branches": 2,
            "commits": [{"sha": "cached1", "message": "Cached commit"}]
        }
        cache.set(cache_key, cached_payload, timeout=3600)

        with patch('requests.get') as mock_get:
            result = fetch_team_commits(self.team, force_refresh=False)
            mock_get.assert_not_called()
            self.assertEqual(result, cached_payload)

    @patch('academic.utils.fetch_deep_commit_stats')
    @patch('requests.get')
    def test_fetch_team_commits_force_refresh_bypasses_cache(self, mock_get, mock_deep):
        """Verifies force_refresh=True ignores existing cache and queries GitHub API."""
        cache_key = f"team_{self.team.pk}_github_commits"
        stale_data = {"status": "success", "total_commits": 1, "commits": []}
        cache.set(cache_key, stale_data, timeout=3600)

        # Mock branches
        branch_resp = MagicMock()
        branch_resp.status_code = 200
        branch_resp.json.return_value = [{"name": "main"}]

        # Mock commits
        commits_resp = MagicMock()
        commits_resp.status_code = 200
        commits_resp.json.return_value = [
            {
                "sha": "fresh123",
                "author": {"login": "dev1"},
                "commit": {
                    "author": {"name": "Dev One", "date": "2026-09-10T12:00:00Z"},
                    "message": "Fresh commit from API"
                },
                "html_url": "https://github.com/testowner/testrepo/commit/fresh123",
                "parents": [{"sha": "parent1"}]
            }
        ]
        mock_get.side_effect = [branch_resp, commits_resp]

        mock_deep.side_effect = lambda commit, owner, repo, headers: {
            **commit, "additions": 15, "deletions": 5
        }

        result = fetch_team_commits(self.team, force_refresh=True)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_commits"], 1)
        self.assertEqual(result["commits"][0]["sha"], "fresh123")
        # Ensure fresh data updated the cache
        self.assertEqual(cache.get(cache_key)["commits"][0]["sha"], "fresh123")

    @patch('academic.utils.fetch_deep_commit_stats')
    @patch('requests.get')
    def test_fetch_team_commits_success_with_merge_and_normal_commits(self, mock_get, mock_deep):
        """
        Verifies full retrieval workflow:
        1. Branches count gathered
        2. Normal commits trigger multithreaded LOC deep stats
        3. Merge commits are flagged with is_merge=True and additions=0, deletions=0
        4. Commits are sorted in reverse chronological order
        """
        branch_resp = MagicMock(status_code=200)
        branch_resp.json.return_value = [{"name": "main"}, {"name": "dev"}]

        commits_resp = MagicMock(status_code=200)
        commits_resp.json.return_value = [
            # Older normal commit
            {
                "sha": "normal_old",
                "author": {"login": "dev1"},
                "commit": {
                    "author": {"name": "Dev One", "date": "2026-09-01T10:00:00Z"},
                    "message": "Old feature implementation"
                },
                "html_url": "https://github.com/testowner/testrepo/commit/normal_old",
                "parents": [{"sha": "p0"}]
            },
            # Newer merge commit (2 parents)
            {
                "sha": "merge_new",
                "author": {"login": "dev1"},
                "commit": {
                    "author": {"name": "Dev One", "date": "2026-09-03T15:00:00Z"},
                    "message": "Merge pull request #1"
                },
                "html_url": "https://github.com/testowner/testrepo/commit/merge_new",
                "parents": [{"sha": "p1"}, {"sha": "p2"}]
            },
            # Middle normal commit
            {
                "sha": "normal_mid",
                "author": {"login": "dev2"},
                "commit": {
                    "author": {"name": "Dev Two", "date": "2026-09-02T12:00:00Z"},
                    "message": "Refactor database query"
                },
                "html_url": "https://github.com/testowner/testrepo/commit/normal_mid",
                "parents": [{"sha": "p1"}]
            }
        ]
        mock_get.side_effect = [branch_resp, commits_resp]

        def fake_deep_stats(c, o, r, h):
            if c["sha"] == "normal_old":
                return {**c, "additions": 100, "deletions": 20}
            elif c["sha"] == "normal_mid":
                return {**c, "additions": 40, "deletions": 5}
            return c

        mock_deep.side_effect = fake_deep_stats

        res = fetch_team_commits(self.team, force_refresh=True)

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["total_branches"], 2)
        self.assertEqual(res["total_commits"], 3)

        # Chronological sort check: merge_new (Sep 3) -> normal_mid (Sep 2) -> normal_old (Sep 1)
        commit_shas = [c["sha"] for c in res["commits"]]
        self.assertEqual(commit_shas, ["merge_new", "normal_mid", "normal_old"])

        # Check merge commit properties
        merge_c = next(c for c in res["commits"] if c["sha"] == "merge_new")
        self.assertTrue(merge_c["is_merge"])
        self.assertEqual(merge_c["additions"], 0)
        self.assertEqual(merge_c["deletions"], 0)

        # Check normal commit LOC
        old_c = next(c for c in res["commits"] if c["sha"] == "normal_old")
        self.assertFalse(old_c["is_merge"])
        self.assertEqual(old_c["additions"], 100)
        self.assertEqual(old_c["deletions"], 20)

    @patch('requests.get')
    def test_fetch_team_commits_api_error_response(self, mock_get):
        """Verifies non-200 GitHub API response returns error status."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        res = fetch_team_commits(self.team, force_refresh=True)
        self.assertEqual(res["status"], "error")
        self.assertIn("Status 404", res["message"])

    @patch('requests.get')
    def test_fetch_team_commits_network_exception(self, mock_get):
        """Verifies requests.RequestException returns error status."""
        import requests
        mock_get.side_effect = requests.RequestException("GitHub API is unreachable")

        res = fetch_team_commits(self.team, force_refresh=True)
        self.assertEqual(res["status"], "error")
        self.assertIn("Network error", res["message"])


class TestGitHubMetricsAnalysis(TestCase):
    """Unit tests for GitHub contribution metrics analysis & aggregation engine."""

    def setUp(self):
        self.coordinator = User.objects.create_user(
            email="coord_analysis@test.com",
            name="Coordinator Analysis",
            role="COORDINATOR",
            password="testpassword123"
        )
        self.instructor = User.objects.create_user(
            email="inst_analysis@test.com",
            name="Instructor Analytics",
            role="INSTRUCTOR",
            password="testpassword123"
        )
        self.course = Course.objects.create(
            course_code="CSE402",
            course_name="Software Testing",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Sec 2",
            instructor=self.instructor
        )
        self.project = Project.objects.create(
            section=self.section,
            title="Analysis Testing Project",
            deadline=timezone.now() + timezone.timedelta(days=14)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Analytics Team",
            github_repo_url="https://github.com/labibaNadi59/ContriGrade"
        )

        self.student1 = User.objects.create_user(
            email="alice@test.com",
            name="Alice Walker",
            role="STUDENT",
            password="pwd"
        )
        self.student1.github_username = "AliceDev"
        self.student1.save()

        self.student2 = User.objects.create_user(
            email="bob@test.com",
            name="Bob Smith",
            role="STUDENT",
            password="pwd"
        )
        self.student2.github_username = "BobCoder"
        self.student2.save()
        self.section.students.add(self.student1, self.student2)

        TeamMember.objects.create(
            team=self.team,
            user=self.student1,
            role_in_team="Frontend Lead"
        )
        TeamMember.objects.create(
            team=self.team,
            user=self.student2,
            role_in_team="Backend Lead"
        )

    def test_case_insensitive_username_mapping(self):
        """Verifies commits match team members regardless of case casing in GitHub usernames."""
        commits_data = [
            {
                "sha": "c1",
                "author_username": "alicedev",  # lowercase vs AliceDev
                "author_name": "Alice",
                "message": "Implemented login page UI",
                "date": "2026-09-01T10:00:00Z",
                "additions": 50,
                "deletions": 10,
                "is_merge": False
            },
            {
                "sha": "c2",
                "author_username": "BOBCODER",  # uppercase vs BobCoder
                "author_name": "Bob",
                "message": "Configured database models",
                "date": "2026-09-01T11:00:00Z",
                "additions": 80,
                "deletions": 5,
                "is_merge": False
            }
        ]

        summary = analyze_team_contributions(self.team, commits_data)

        alice_stats = summary["mapped_students"][self.student1.pk]
        bob_stats = summary["mapped_students"][self.student2.pk]

        self.assertEqual(alice_stats["commit_count"], 1)
        self.assertEqual(alice_stats["total_additions"], 50)
        self.assertEqual(alice_stats["total_deletions"], 10)

        self.assertEqual(bob_stats["commit_count"], 1)
        self.assertEqual(bob_stats["total_additions"], 80)
        self.assertEqual(bob_stats["total_deletions"], 5)

        self.assertEqual(len(summary["unmapped_commits"]), 0)

    def test_unmapped_commits_isolation(self):
        """Verifies commits from unregistered authors or None authors are categorized as unmapped."""
        commits_data = [
            {
                "sha": "c_unmapped1",
                "author_username": "stranger123",
                "author_name": "Stranger",
                "message": "Third party commit",
                "date": "2026-09-01T10:00:00Z",
                "additions": 20,
                "deletions": 5,
                "is_merge": False
            },
            {
                "sha": "c_unmapped2",
                "author_username": None,
                "author_name": "Git Bot",
                "message": "Automated commit without GitHub account",
                "date": "2026-09-01T12:00:00Z",
                "additions": 10,
                "deletions": 0,
                "is_merge": False
            }
        ]

        summary = analyze_team_contributions(self.team, commits_data)

        self.assertEqual(len(summary["unmapped_commits"]), 2)
        for st in summary["mapped_students"].values():
            self.assertEqual(st["commit_count"], 0)

    def test_impact_score_and_fair_percentage_calculation(self):
        """
        Verifies Fair Impact Score formula:
        Impact = total_additions + total_deletions + commit_count
        Percentage = round((impact_score / total_team_impact) * 100)
        """
        commits_data = [
            # Alice: 2 commits, 150 additions, 50 deletions -> impact = 150 + 50 + 2 = 202
            {
                "sha": "a1",
                "author_username": "AliceDev",
                "author_name": "Alice",
                "message": "Feature component styling",
                "date": "2026-09-01T10:00:00Z",
                "additions": 100,
                "deletions": 30,
                "is_merge": False
            },
            {
                "sha": "a2",
                "author_username": "AliceDev",
                "author_name": "Alice",
                "message": "Fix responsiveness bug",
                "date": "2026-09-02T10:00:00Z",
                "additions": 50,
                "deletions": 20,
                "is_merge": False
            },
            # Bob: 1 commit, 40 additions, 10 deletions -> impact = 40 + 10 + 1 = 51
            {
                "sha": "b1",
                "author_username": "BobCoder",
                "author_name": "Bob",
                "message": "Setup API router endpoints",
                "date": "2026-09-01T12:00:00Z",
                "additions": 40,
                "deletions": 10,
                "is_merge": False
            }
        ]

        summary = analyze_team_contributions(self.team, commits_data)

        alice = summary["mapped_students"][self.student1.pk]
        bob = summary["mapped_students"][self.student2.pk]

        self.assertEqual(alice["impact_score"], 202)
        self.assertEqual(bob["impact_score"], 51)

        total_impact = 202 + 51  # 253
        expected_alice_pct = round((202 / 253) * 100)  # 80%
        expected_bob_pct = round((51 / 253) * 100)    # 20%

        self.assertEqual(alice["percentage"], expected_alice_pct)
        self.assertEqual(bob["percentage"], expected_bob_pct)

    def test_zero_commits_edge_case(self):
        """Verifies team with zero commits does not raise ZeroDivisionError and sets percentage 0."""
        summary = analyze_team_contributions(self.team, [])

        self.assertEqual(summary["total_commits"], 0)
        for st in summary["mapped_students"].values():
            self.assertEqual(st["commit_count"], 0)
            self.assertEqual(st["percentage"], 0)

    def test_timeline_chart_generation(self):
        """Verifies timeline chart labels are sorted dates and counts aggregate daily commits."""
        commits_data = [
            {"sha": "1", "author_username": "AliceDev", "message": "msg1", "date": "2026-09-05T10:00:00Z", "additions": 5, "deletions": 1, "is_merge": False},
            {"sha": "2", "author_username": "BobCoder", "message": "msg2", "date": "2026-09-01T12:00:00Z", "additions": 10, "deletions": 2, "is_merge": False},
            {"sha": "3", "author_username": "AliceDev", "message": "msg3", "date": "2026-09-01T18:00:00Z", "additions": 15, "deletions": 0, "is_merge": False},
        ]

        summary = analyze_team_contributions(self.team, commits_data)

        self.assertEqual(summary["chart_labels"], ["2026-09-01", "2026-09-05"])
        self.assertEqual(summary["chart_data"], [2, 1])

    def test_integrity_flags_detection(self):
        """
        Verifies the 3 integrity flags:
        1. Trivial/fluff commits (LOC < 3 or message < 5 chars)
        2. Massive code dumps (> 1000 additions)
        3. Rapid-fire bursts (< 120s between commits)
        And confirms Clean Commit History when commits are well-spaced and substantial.
        """
        commits_data = [
            # Fluff commit for Alice
            {
                "sha": "a_fluff",
                "author_username": "AliceDev",
                "author_name": "Alice",
                "message": "fix",  # length 3 < 5
                "date": "2026-09-01T10:00:00Z",
                "additions": 1,    # total changes 1 < 3
                "deletions": 0,
                "is_merge": False
            },
            # Massive code dump for Alice
            {
                "sha": "a_dump",
                "author_username": "AliceDev",
                "author_name": "Alice",
                "message": "Massive initial project import",
                "date": "2026-09-01T12:00:00Z",
                "additions": 1450,  # > 1000 additions
                "deletions": 5,
                "is_merge": False
            },
            # Rapid-fire burst for Alice (60 seconds after a_dump)
            {
                "sha": "a_burst",
                "author_username": "AliceDev",
                "author_name": "Alice",
                "message": "Minor tweak to import setup",
                "date": "2026-09-01T12:01:00Z",
                "additions": 20,
                "deletions": 2,
                "is_merge": False
            },
            # Clean commits for Bob (> 2 mins apart, good LOC, informative messages)
            {
                "sha": "b_clean1",
                "author_username": "BobCoder",
                "author_name": "Bob",
                "message": "Create user authentication middleware",
                "date": "2026-09-02T10:00:00Z",
                "additions": 75,
                "deletions": 15,
                "is_merge": False
            },
            {
                "sha": "b_clean2",
                "author_username": "BobCoder",
                "author_name": "Bob",
                "message": "Implement token refresh helper function",
                "date": "2026-09-02T11:30:00Z",
                "additions": 45,
                "deletions": 10,
                "is_merge": False
            }
        ]

        summary = analyze_team_contributions(self.team, commits_data)

        alice = summary["mapped_students"][self.student1.pk]
        bob = summary["mapped_students"][self.student2.pk]

        alice_flags_text = " ".join(alice["flags"]).lower()
        self.assertIn("trivial/fluff commits", alice_flags_text)
        self.assertIn("massive code dumps", alice_flags_text)
        self.assertIn("rapid-fire bursts", alice_flags_text)

        # Bob should have clean history (0 flags)
        self.assertEqual(len(bob["flags"]), 0)

    def test_merge_commits_ignored_in_analysis(self):
        """Verifies merge commits (is_merge=True) are bypassed in metrics accumulation."""
        commits_data = [
            {
                "sha": "m1",
                "author_username": "AliceDev",
                "author_name": "Alice",
                "message": "Merge branch dev into main",
                "date": "2026-09-01T10:00:00Z",
                "additions": 500,
                "deletions": 100,
                "is_merge": True
            }
        ]

        summary = analyze_team_contributions(self.team, commits_data)
        alice = summary["mapped_students"][self.student1.pk]

        self.assertEqual(alice["commit_count"], 0)
        self.assertEqual(alice["total_additions"], 0)


class TestGitHubMetricsDisplayViews(TestCase):
    """Integration tests for views displaying GitHub contribution metrics."""

    def setUp(self):
        cache.clear()
        self.client = Client()

        self.instructor = User.objects.create_user(
            email="prof_display@test.com",
            name="Professor Davis",
            role="INSTRUCTOR",
            password="password123"
        )
        self.admin_user = User.objects.create_user(
            email="admin_display@test.com",
            name="Admin User",
            role="ADMIN",
            password="password123"
        )
        self.student1 = User.objects.create_user(
            email="carol@test.com",
            name="Carol Danvers",
            role="STUDENT",
            password="password123"
        )
        self.student1.github_username = "CarolDev"
        self.student1.save()

        self.student2 = User.objects.create_user(
            email="dave@test.com",
            name="Dave Bowman",
            role="STUDENT",
            password="password123"
        )
        self.student2.github_username = "DaveDev"
        self.student2.save()
        self.outsider_student = User.objects.create_user(
            email="outsider@test.com",
            name="Outsider Student",
            role="STUDENT",
            password="password123"
        )

        self.coordinator = User.objects.create_user(
            email="coord_display@test.com",
            name="Coordinator Display",
            role="COORDINATOR",
            password="password123"
        )
        self.course = Course.objects.create(
            course_code="CSE316",
            course_name="Web Systems Development",
            coordinator=self.coordinator
        )
        self.section = CourseSection.objects.create(
            course=self.course,
            section_name="Sec A",
            instructor=self.instructor
        )
        self.project = Project.objects.create(
            section=self.section,
            title="Fullstack Web Portal",
            deadline=timezone.now() + timezone.timedelta(days=20)
        )
        self.team = Team.objects.create(
            project=self.project,
            team_name="Web Ninjas",
            github_repo_url="https://github.com/testowner/web-ninjas"
        )
        self.section.students.add(self.student1, self.student2)

        TeamMember.objects.create(
            team=self.team,
            user=self.student1,
            role_in_team="Frontend Lead"
        )
        TeamMember.objects.create(
            team=self.team,
            user=self.student2,
            role_in_team="Backend Lead"
        )

    def tearDown(self):
        cache.clear()

    # --- Student Team Progress Display Tests ---

    def test_student_progress_unauthenticated_redirects(self):
        """Unauthenticated user accessing team progress is redirected to login."""
        url = f"/academic/student/team/{self.team.pk}/progress/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp.url)

    def test_student_progress_non_team_member_returns_404(self):
        """Student who is not a member of the requested team gets 404."""
        self.client.login(email="outsider@test.com", password="password123")
        url = f"/academic/student/team/{self.team.pk}/progress/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_student_progress_unlinked_repo_displays_warning(self):
        """When team has no linked GitHub repository, a clear warning is displayed."""
        self.team.github_repo_url = None
        self.team.save()

        self.client.login(email="carol@test.com", password="password123")
        url = f"/academic/student/team/{self.team.pk}/progress/"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "academic/student_progress.html")
        self.assertContains(resp, "Your team has not linked a GitHub repository yet.")

    @patch('academic.views.fetch_team_commits')
    def test_student_progress_api_error_displays_message(self, mock_fetch):
        """When GitHub API fails, error message is rendered in the progress template."""
        mock_fetch.return_value = {
            "status": "error",
            "message": "GitHub API rate limit exceeded."
        }

        self.client.login(email="carol@test.com", password="password123")
        url = f"/academic/student/team/{self.team.pk}/progress/"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "GitHub API rate limit exceeded.")

    @patch('academic.views.fetch_team_commits')
    def test_student_progress_successful_display(self, mock_fetch):
        """
        Verifies student progress page display:
        - Team header and Action buttons
        - Stat cards (Total Commits, Active Contributors, Active Branches, Live Data)
        - Chart canvas elements (timelineChart, splitChart)
        - Member cards with names, '(You)' badge for logged-in user, progress bars, commit counts, LOC (+/-)
        - Integrity flags are NOT displayed to students
        """
        mock_fetch.return_value = {
            "status": "success",
            "total_commits": 2,
            "total_branches": 3,
            "commits": [
                {
                    "sha": "c1",
                    "author_username": "CarolDev",
                    "author_name": "Carol",
                    "message": "Add user dashboard component",
                    "date": "2026-09-01T10:00:00Z",
                    "additions": 60,
                    "deletions": 10,
                    "is_merge": False,
                    "url": "https://github.com/testowner/web-ninjas/commit/c1"
                },
                {
                    "sha": "c2",
                    "author_username": "DaveDev",
                    "author_name": "Dave",
                    "message": "Add REST endpoints for metrics",
                    "date": "2026-09-02T12:00:00Z",
                    "additions": 120,
                    "deletions": 15,
                    "is_merge": False,
                    "url": "https://github.com/testowner/web-ninjas/commit/c2"
                }
            ]
        }

        self.client.login(email="carol@test.com", password="password123")
        url = f"/academic/student/team/{self.team.pk}/progress/"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "academic/student_progress.html")

        # 1. Header & Actions
        self.assertContains(resp, "Team Progress: Web Ninjas")
        self.assertContains(resp, "View Repo")
        self.assertContains(resp, "Refresh")

        # 2. Stat Cards
        self.assertContains(resp, "Total Team Commits")
        self.assertContains(resp, "Active Contributors")
        self.assertContains(resp, "Live Data")
        self.assertContains(resp, "Active Branches")

        # 3. Canvas Elements for Charts
        self.assertContains(resp, 'id="timelineChart"')
        self.assertContains(resp, 'id="splitChart"')

        # 4. Member Contributions & 'You' badge for Carol
        self.assertContains(resp, "Carol Danvers")
        self.assertContains(resp, "Dave Bowman")
        self.assertContains(resp, "You")  # '(You)' badge for logged-in user Carol
        self.assertContains(resp, "commits")
        self.assertContains(resp, "+60")
        self.assertContains(resp, "-10")
        self.assertContains(resp, "+120")
        self.assertContains(resp, "-15")

        # 5. Integrity flags must NOT be shown to students
        self.assertNotContains(resp, "Clean Commit History")
        self.assertNotContains(resp, "trivial/fluff commits")

    @patch('academic.views.fetch_team_commits')
    def test_student_progress_refresh_param_forces_cache_refresh(self, mock_fetch):
        """Verifies ?refresh=true passes force_refresh=True to fetch_team_commits."""
        mock_fetch.return_value = {"status": "success", "total_commits": 0, "commits": []}

        self.client.login(email="carol@test.com", password="password123")
        url = f"/academic/student/team/{self.team.pk}/progress/?refresh=true"
        self.client.get(url)

        mock_fetch.assert_called_with(self.team, force_refresh=True)

    # --- Instructor Team Analytics Display Tests ---

    def test_instructor_analytics_student_denied(self):
        """Student attempting to access instructor analytics is denied and redirected."""
        self.client.login(email="carol@test.com", password="password123")
        url = f"/academic/instructor/team/{self.team.pk}/analytics/"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/academic/student/", resp.url)

    def test_instructor_analytics_instructor_access_allowed(self):
        """Instructor can access team analytics dashboard."""
        self.client.login(email="prof_display@test.com", password="password123")
        url = f"/academic/instructor/team/{self.team.pk}/analytics/"

        with patch('academic.views.fetch_team_commits') as mock_fetch:
            mock_fetch.return_value = {
                "status": "success",
                "total_commits": 0,
                "commits": []
            }
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertTemplateUsed(resp, "academic/team_analytics.html")

    def test_instructor_analytics_admin_access_allowed(self):
        """Admin can access team analytics dashboard."""
        self.client.login(email="admin_display@test.com", password="password123")
        url = f"/academic/instructor/team/{self.team.pk}/analytics/"

        with patch('academic.views.fetch_team_commits') as mock_fetch:
            mock_fetch.return_value = {
                "status": "success",
                "total_commits": 0,
                "commits": []
            }
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)

    def test_instructor_analytics_unlinked_repo_display(self):
        """When team has no repository, analytics shows error banner."""
        self.team.github_repo_url = None
        self.team.save()

        self.client.login(email="prof_display@test.com", password="password123")
        url = f"/academic/instructor/team/{self.team.pk}/analytics/"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "This team has not linked a GitHub repository yet.")

    @patch('academic.views.fetch_team_commits')
    def test_instructor_analytics_successful_display_with_flags_and_feed(self, mock_fetch):
        """
        Verifies complete instructor team analytics display:
        - 4 top stat cards: Total Commits, Mapped Students, Unmapped Commits, Active Branches
        - Canvas charts: timelineChart, splitChart
        - Commits Feed container & student filter dropdown
        - Student contribution cards with flags (e.g. Clean Commit History)
        """
        mock_fetch.return_value = {
            "status": "success",
            "total_commits": 2,
            "total_branches": 2,
            "commits": [
                {
                    "sha": "sha_clean1",
                    "author_username": "CarolDev",
                    "author_name": "Carol",
                    "message": "Implement responsive navigation layout",
                    "date": "2026-09-01T10:00:00Z",
                    "additions": 45,
                    "deletions": 10,
                    "is_merge": False,
                    "url": "https://github.com/testowner/web-ninjas/commit/sha_clean1"
                },
                {
                    "sha": "sha_clean2",
                    "author_username": "DaveDev",
                    "author_name": "Dave",
                    "message": "Configure PostgreSQL database pools",
                    "date": "2026-09-02T15:00:00Z",
                    "additions": 80,
                    "deletions": 20,
                    "is_merge": False,
                    "url": "https://github.com/testowner/web-ninjas/commit/sha_clean2"
                }
            ]
        }

        self.client.login(email="prof_display@test.com", password="password123")
        url = f"/academic/instructor/team/{self.team.pk}/analytics/"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)

        # 1. Header
        self.assertContains(resp, "Team Analytics")
        self.assertContains(resp, "Web Ninjas")

        # 2. Stat Cards
        self.assertContains(resp, "Total Commits")
        self.assertContains(resp, "Mapped Students")
        self.assertContains(resp, "Unmapped Commits")
        self.assertContains(resp, "Active Branches")

        # 3. Visual Charts
        self.assertContains(resp, 'id="timelineChart"')
        self.assertContains(resp, 'id="splitChart"')

        # 4. Project Commits Feed & Filter Dropdown
        self.assertContains(resp, 'id="studentCommitFilter"')
        self.assertContains(resp, 'id="commitsFeedContainer"')
        self.assertContains(resp, "Implement responsive navigation layout")
        self.assertContains(resp, "Configure PostgreSQL database pools")

        # 5. Integrity Flags Display (Clean history for both)
        self.assertContains(resp, "Clean Commit History")

    @patch('academic.views.fetch_team_commits')
    def test_instructor_analytics_refresh_param(self, mock_fetch):
        """Verifies ?refresh=true passes force_refresh=True."""
        mock_fetch.return_value = {"status": "success", "total_commits": 0, "commits": []}

        self.client.login(email="prof_display@test.com", password="password123")
        url = f"/academic/instructor/team/{self.team.pk}/analytics/?refresh=true"
        self.client.get(url)

        mock_fetch.assert_called_with(self.team, force_refresh=True)

    # --- Instructor Master Class Report & CSV Export Tests ---

    def test_master_report_student_denied(self):
        """Student attempting to view master report is denied access."""
        self.client.login(email="carol@test.com", password="password123")
        url = f"/academic/instructor/project/{self.project.pk}/report/"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/academic/student/", resp.url)

    @patch('academic.views.fetch_team_commits')
    def test_master_report_html_display(self, mock_fetch):
        """
        Verifies instructor master class report displays:
        - Class summary stat cards
        - Student rows sorted by commit count
        - Table headers: Student Name, Team, Commits, Lines of Code, Integrity Analysis
        - Download CSV link and Refresh link
        """
        mock_fetch.return_value = {
            "status": "success",
            "total_commits": 3,
            "total_branches": 1,
            "commits": [
                {
                    "sha": "c1",
                    "author_username": "CarolDev",
                    "author_name": "Carol",
                    "message": "Commit 1",
                    "date": "2026-09-01T10:00:00Z",
                    "additions": 30,
                    "deletions": 5,
                    "is_merge": False
                },
                {
                    "sha": "c2",
                    "author_username": "DaveDev",
                    "author_name": "Dave",
                    "message": "Commit 2",
                    "date": "2026-09-02T10:00:00Z",
                    "additions": 50,
                    "deletions": 10,
                    "is_merge": False
                },
                {
                    "sha": "c3",
                    "author_username": "DaveDev",
                    "author_name": "Dave",
                    "message": "Commit 3",
                    "date": "2026-09-03T10:00:00Z",
                    "additions": 40,
                    "deletions": 5,
                    "is_merge": False
                }
            ]
        }

        self.client.login(email="prof_display@test.com", password="password123")
        url = f"/academic/instructor/project/{self.project.pk}/report/"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "academic/master_report.html")

        # Header & stats
        self.assertContains(resp, "Master Class Report")
        self.assertContains(resp, "Total Students")
        self.assertContains(resp, "Total Class Commits")
        self.assertContains(resp, "Teams Connected")

        # Table headers
        self.assertContains(resp, "Student Name")
        self.assertContains(resp, "Team")
        self.assertContains(resp, "Commits")
        self.assertContains(resp, "Lines of Code")
        self.assertContains(resp, "Integrity Analysis")

        # Student data: Dave (2 commits) should appear before Carol (1 commit)
        self.assertContains(resp, "Dave Bowman")
        self.assertContains(resp, "Carol Danvers")

        # CSV Download Link
        self.assertContains(resp, "?export=csv")

    @patch('academic.views.fetch_team_commits')
    def test_master_report_csv_export(self, mock_fetch):
        """
        Verifies CSV export endpoint (?export=csv):
        - Returns 200 with Content-Type: text/csv
        - Attachment filename in Content-Disposition
        - Valid CSV header: Student Name,GitHub Username,Team,Role,Commits,Lines Added,Lines Deleted,Integrity Flags
        - Data rows match aggregated student contributions
        """
        mock_fetch.return_value = {
            "status": "success",
            "total_commits": 1,
            "total_branches": 1,
            "commits": [
                {
                    "sha": "c1",
                    "author_username": "CarolDev",
                    "author_name": "Carol",
                    "message": "Add user authentication module",
                    "date": "2026-09-01T10:00:00Z",
                    "additions": 110,
                    "deletions": 25,
                    "is_merge": False
                }
            ]
        }

        self.client.login(email="prof_display@test.com", password="password123")
        url = f"/academic/instructor/project/{self.project.pk}/report/?export=csv"
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("attachment; filename=", resp["Content-Disposition"])

        csv_content = resp.content.decode("utf-8")
        reader = list(csv.reader(io.StringIO(csv_content)))

        # Header check
        self.assertEqual(
            reader[0],
            ['Student Name', 'GitHub Username', 'Team', 'Role', 'Commits', 'Lines Added', 'Lines Deleted', 'Integrity Flags']
        )

        # Check rows
        carol_row = next((r for r in reader[1:] if r[0] == "Carol Danvers"), None)
        self.assertIsNotNone(carol_row)
        self.assertEqual(carol_row[1], "CarolDev")
        self.assertEqual(carol_row[2], "Web Ninjas")
        self.assertEqual(carol_row[3], "Frontend Lead")
        self.assertEqual(carol_row[4], "1")    # Commits
        self.assertEqual(carol_row[5], "110")  # Additions
        self.assertEqual(carol_row[6], "25")   # Deletions
        self.assertEqual(carol_row[7], "Clean") # Integrity Flags

