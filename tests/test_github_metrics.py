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
