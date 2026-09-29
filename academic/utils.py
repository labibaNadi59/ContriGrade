import requests
from django.conf import settings
import re
from datetime import datetime
from .models import TeamMember
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

def validate_github_connection():
    """Pings the GitHub API to verify the token is valid and active."""
    token = settings.GITHUB_API_TOKEN

    if not token:
        return {"status": "error", "message": "GitHub API token is missing from environment variables."}

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        # Ping the authenticated user endpoint
        response = requests.get("https://api.github.com/user", headers=headers, timeout=5)

        if response.status_code == 200:
            data = response.json()
            return {
                "status": "success",
                "message": f"Connected successfully as {data.get('login')}",
                "rate_limit": response.headers.get('X-RateLimit-Remaining')
            }
        elif response.status_code == 401:
            return {"status": "error", "message": "Authentication failed. The token is invalid or expired."}
        else:
            return {"status": "error", "message": f"GitHub API returned status code {response.status_code}."}

    except requests.RequestException as e:
        return {"status": "error", "message": f"Network error connecting to GitHub: {str(e)}"}




def validate_github_repo_url(repo_url):
    """
    Checks if a URL is a valid GitHub repo format, then pings the GitHub API
    to confirm the repository exists and is accessible.
    """
    if not repo_url:
        return {"valid": False, "error": "No URL provided."}

    # 1. Format Check: Must match https://github.com/owner/repo
    pattern = r'^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/?$'
    match = re.match(pattern, repo_url.strip())

    if not match:
        return {"valid": False, "error": "Invalid format. Use: https://github.com/owner/repo"}

    owner, repo = match.groups()

    # Clean up '.git' if the student accidentally pasted a clone link
    if repo.endswith('.git'):
        repo = repo[:-4]

    # 2. API Existence Check
    token = settings.GITHUB_API_TOKEN
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        response = requests.get(api_url, headers=headers, timeout=5)

        if response.status_code == 200:
            return {"valid": True, "error": None, "clean_url": f"https://github.com/{owner}/{repo}"}
        elif response.status_code == 404:
            return {"valid": False,
                    "error": f"Repository '{owner}/{repo}' not found. Ensure it is public or the System API token has access to it."}
        elif response.status_code == 401:
            return {"valid": False, "error": "System Error: GitHub API token is invalid."}
        else:
            return {"valid": False, "error": f"GitHub API error: Status {response.status_code}"}

    except requests.RequestException as e:
        return {"valid": False, "error": "Network error while connecting to GitHub."}


def fetch_deep_commit_stats(commit_info, owner, repo, headers):
    """Worker function to fetch LOC stats for a single commit."""
    sha = commit_info['sha']
    deep_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"

    try:
        resp = requests.get(deep_url, headers=headers, timeout=5)
        if resp.status_code == 200:
            stats = resp.json().get('stats', {})
            commit_info['additions'] = stats.get('additions', 0)
            commit_info['deletions'] = stats.get('deletions', 0)
        else:
            commit_info['additions'] = 0
            commit_info['deletions'] = 0
    except requests.RequestException:
        commit_info['additions'] = 0
        commit_info['deletions'] = 0

    return commit_info


def fetch_team_commits(team):
    """
    Fetches up to 100 recent commits and uses multithreading to rapidly
    gather Lines of Code (LOC) stats in parallel.
    """
    if not team.github_repo_url:
        return {"status": "error", "message": "No repository linked to this team."}

    pattern = r'^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/?$'
    match = re.match(pattern, team.github_repo_url)

    if not match:
        return {"status": "error", "message": "Invalid repository URL format."}

    owner, repo = match.groups()
    token = getattr(settings, 'GITHUB_API_TOKEN', None)

    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"

    # Step 1: Fetch the initial list of commits (Just 1 fast API call)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=100&page=1"

    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"GitHub API error: Status {response.status_code}"}

        page_commits = response.json()
    except requests.RequestException as e:
        return {"status": "error", "message": f"Network error: {str(e)}"}

    # Step 2: Clean the base data
    base_commits = []
    for item in page_commits:
        github_account = item.get('author')
        base_commits.append({
            'sha': item['sha'],
            'author_username': github_account.get('login') if github_account else None,
            'author_name': item['commit']['author']['name'],
            'message': item['commit']['message'],
            'date': item['commit']['author']['date'],
            'url': item['html_url']
        })

    # Step 3: Fetch Deep Stats Concurrently (The Speed Boost!)
    final_commits = []

    # Use 20 parallel workers to blast through the API requests instantly
    with ThreadPoolExecutor(max_workers=20) as executor:
        # Submit all jobs
        future_to_commit = {
            executor.submit(fetch_deep_commit_stats, commit, owner, repo, headers): commit
            for commit in base_commits
        }

        # Collect results as they finish
        for future in as_completed(future_to_commit):
            final_commits.append(future.result())

    # Sort them back into chronological order (since threads finish at random times)
    final_commits.sort(key=lambda x: x['date'], reverse=True)

    return {
        "status": "success",
        "total_commits": len(final_commits),
        "commits": final_commits
    }



def analyze_team_contributions(team, commits_data):
    """
    Maps raw GitHub commits to registered TeamMembers and calculates summary stats.
    """
    # 1. Fetch all students actually assigned to this team in the database
    members = TeamMember.objects.filter(team=team).select_related('user')

    # 2. Build a fast lookup dictionary using github_username as the key
    # We use .lower() to ensure case-insensitive matching (e.g., labibaNadi59 vs LabibaNadi59)
    member_lookup = {}
    for member in members:
        if member.user.github_username:
            member_lookup[member.user.github_username.lower()] = member

    # 3. Initialize the summary dashboard structure
    summary = {
        'mapped_students': {},
        'unmapped_commits': [],
        'total_commits': len(commits_data),
        'chart_labels': [],
        'chart_data': []
    }

    # Pre-fill the dictionary for every team member (even if they have 0 commits)
    for member in members:
        summary['mapped_students'][member.user.pk] = {
            'name': member.user.name,
            'github_username': member.user.github_username,
            'role': member.role_in_team,
            'commit_count': 0,
            'total_additions': 0,
            'total_deletions': 0,
            'commits': []
        }

    # 4. Map each commit to a student
    for commit in commits_data:
        gh_username = commit.get('author_username')

        if gh_username and gh_username.lower() in member_lookup:
            matched_member = member_lookup[gh_username.lower()]
            student_data = summary['mapped_students'][matched_member.user.pk]

            student_data['commit_count'] += 1
            student_data['total_additions'] += commit.get('additions', 0)  # NEW
            student_data['total_deletions'] += commit.get('deletions', 0)  # NEW
            student_data['commits'].append(commit)
        else:
            # No match found (could be the instructor, an external contributor, or a misconfigured local git client)
            summary['unmapped_commits'].append(commit)

    timeline_dict = defaultdict(int)
    for commit in commits_data:
        # Extract just the YYYY-MM-DD from '2026-09-28T14:32:00Z'
        day_str = commit.get('date', '')[:10]
        if day_str:
            timeline_dict[day_str] += 1

    # Sort dates chronologically
    sorted_dates = sorted(timeline_dict.keys())
    summary['chart_labels'] = sorted_dates
    summary['chart_data'] = [timeline_dict[d] for d in sorted_dates]

    for pk, student in summary['mapped_students'].items():
        student['flags'] = []
        fluff_count = 0
        dump_count = 0
        burst_count = 0

        # Sort commits chronologically (oldest to newest) to check for time bursts
        student_commits = sorted(student['commits'], key=lambda x: x['date'])

        for i, commit in enumerate(student_commits):
            total_changes = commit.get('additions', 0) + commit.get('deletions', 0)
            msg = commit.get('message', '').strip()

            # 1. Fluff Detection
            if total_changes < 3 or len(msg) < 5:
                fluff_count += 1

            # 2. Massive Dump Detection
            if commit.get('additions', 0) > 1000:
                dump_count += 1

            # 3. Burst Detection (Check time difference with the PREVIOUS commit)
            if i > 0:
                # GitHub dates look like "2026-09-28T14:32:00Z"
                date_format = "%Y-%m-%dT%H:%M:%SZ"
                try:
                    current_date = datetime.strptime(commit['date'], date_format)
                    prev_date = datetime.strptime(student_commits[i - 1]['date'], date_format)

                    # If commits are less than 120 seconds apart
                    if (current_date - prev_date).total_seconds() < 120:
                        burst_count += 1
                except ValueError:
                    pass  # Ignore if date parsing fails

        # Attach warnings to the student's profile if thresholds are met
        if fluff_count > 0:
            student['flags'].append(f"{fluff_count} trivial/fluff commits (Very low LOC or short messages).")
        if dump_count > 0:
            student['flags'].append(f"{dump_count} massive code dumps (>1,000 additions in a single commit).")
        if burst_count > 0:
            student['flags'].append(f"{burst_count} rapid-fire bursts (Commits pushed within 2 minutes of each other).")

    return summary