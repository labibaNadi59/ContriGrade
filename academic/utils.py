import requests
from django.conf import settings
import re


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