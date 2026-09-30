import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import django
from unittest.mock import patch, MagicMock

# Configure Django settings for test runner
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()

import unittest
from academic.utils import (
    validate_github_connection,
    validate_github_repo_url,
    fetch_deep_commit_stats,
    analyze_team_contributions
)
from academic.models import Team, TeamMember, Course, CourseSection, Project
from accounts.models import User


class TestGitHubBackendUnit(unittest.TestCase):

    @patch('requests.get')
    def test_validate_github_connection_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"login": "testuser"}
        mock_resp.headers = {"X-RateLimit-Remaining": "4950"}
        mock_get.return_value = mock_resp

        result = validate_github_connection()
        self.assertEqual(result["status"], "success")
        self.assertIn("Connected successfully as testuser", result["message"])
        self.assertEqual(result["rate_limit"], "4950")

    @patch('requests.get')
    def test_validate_github_connection_invalid_token(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp

        result = validate_github_connection()
        self.assertEqual(result["status"], "error")
        self.assertIn("Authentication failed", result["message"])

    def test_validate_github_repo_url_invalid_formats(self):
        # Empty
        res = validate_github_repo_url("")
        self.assertFalse(res["valid"])

        # Not GitHub domain
        res = validate_github_repo_url("https://gitlab.com/owner/repo")
        self.assertFalse(res["valid"])

        # Incomplete path
        res = validate_github_repo_url("https://github.com/onlyowner")
        self.assertFalse(res["valid"])

    @patch('requests.get')
    def test_validate_github_repo_url_success_with_git_suffix(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        # URL with .git suffix should be cleanly stripped
        res = validate_github_repo_url("https://github.com/octocat/Hello-World.git")
        self.assertTrue(res["valid"])
        self.assertEqual(res["clean_url"], "https://github.com/octocat/Hello-World")

    @patch('requests.get')
    def test_validate_github_repo_url_not_found(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        res = validate_github_repo_url("https://github.com/octocat/NonExistentRepo")
        self.assertFalse(res["valid"])
        self.assertIn("not found", res["error"].lower())

    @patch('requests.get')
    def test_fetch_deep_commit_stats_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"stats": {"additions": 45, "deletions": 12}}
        mock_get.return_value = mock_resp

        commit = {"sha": "abc1234"}
        result = fetch_deep_commit_stats(commit, "owner", "repo", {})
        self.assertEqual(result["additions"], 45)
        self.assertEqual(result["deletions"], 12)

    def test_analyze_team_contributions_integrity_flags(self):
        team = Team.objects.filter(pk=2).first()
        if not team:
            self.skipTest("Team 2 not in database")

        commits_data = [
            # Trivial/fluff commit (additions+deletions < 3 and message < 5)
            {
                "sha": "c1",
                "author_username": "labibaNadi59",
                "author_name": "labiba",
                "message": "fix",
                "date": "2026-09-01T10:00:00Z",
                "additions": 1,
                "deletions": 0,
                "is_merge": False,
            },
            # Massive code dump (> 1000 additions)
            {
                "sha": "c2",
                "author_username": "labibaNadi59",
                "author_name": "labiba",
                "message": "Massive initial dump",
                "date": "2026-09-01T11:00:00Z",
                "additions": 1500,
                "deletions": 20,
                "is_merge": False,
            },
            # Rapid-fire burst (< 120 seconds after c2)
            {
                "sha": "c3",
                "author_username": "labibaNadi59",
                "author_name": "labiba",
                "message": "Quick subsequent commit",
                "date": "2026-09-01T11:01:30Z",
                "additions": 10,
                "deletions": 5,
                "is_merge": False,
            },
        ]

        summary = analyze_team_contributions(team, commits_data)

        # Find student labiba
        labiba_data = None
        for pk, st in summary["mapped_students"].items():
            if (st.get("github_username") or "").lower() == "labibanadi59":
                labiba_data = st
                break

        self.assertIsNotNone(labiba_data)
        self.assertEqual(labiba_data["commit_count"], 3)
        self.assertEqual(labiba_data["total_additions"], 1511)
        self.assertEqual(labiba_data["total_deletions"], 25)

        # Verify integrity flags are raised
        flags_text = " ".join(labiba_data["flags"]).lower()
        self.assertIn("fluff", flags_text)
        self.assertIn("massive code dump", flags_text)
        self.assertIn("burst", flags_text)


if __name__ == '__main__':
    unittest.main()
