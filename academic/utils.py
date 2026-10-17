import requests
from django.conf import settings
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from django.core.cache import cache
from .models import TeamMember, DeliverableContribution, PeerEvaluationScore


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


def fetch_team_commits(team, force_refresh=False):
    """
    Fetches up to 100 recent commits and uses multithreading to rapidly
    gather Lines of Code (LOC) stats in parallel.
    """
    if not team.github_repo_url:
        return {"status": "error", "message": "No repository linked to this team."}

    cache_key = f"team_{team.pk}_github_commits"

    # Check if we already have this data saved in memory
    if not force_refresh:
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data

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

    branches_url = f"https://api.github.com/repos/{owner}/{repo}/branches"
    try:
        branches_res = requests.get(branches_url, headers=headers, timeout=5)
        total_branches = len(branches_res.json()) if branches_res.status_code == 200 else 1
    except requests.RequestException:
        total_branches = 1

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
        # NEW: Keep the merge commit, but tag it so the analytics engine ignores it
        is_merge = len(item.get('parents', [])) > 1

        github_account = item.get('author')
        base_commits.append({
            'sha': item['sha'],
            'author_username': github_account.get('login') if github_account else None,
            'author_name': item['commit']['author']['name'],
            'message': item['commit']['message'],
            'date': item['commit']['author']['date'],
            'url': item['html_url'],
            'is_merge': is_merge
        })

    # Step 3: Fetch Deep Stats Concurrently (The Speed Boost!)

    normal_commits = [c for c in base_commits if not c['is_merge']]
    merge_commits = [c for c in base_commits if c['is_merge']]

    final_commits = []

    # Use 20 parallel workers to blast through the API requests instantly
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_commit = {
            executor.submit(fetch_deep_commit_stats, commit, owner, repo, headers): commit
            for commit in normal_commits
        }
        for future in as_completed(future_to_commit):
            final_commits.append(future.result())

    for mc in merge_commits:
        mc['additions'] = 0
        mc['deletions'] = 0
        final_commits.append(mc)

    # Sort them back into chronological order (since threads finish at random times)
    final_commits.sort(key=lambda x: x['date'], reverse=True)

    result = {
        "status": "success",
        "total_commits": len(final_commits),
        "total_branches": total_branches,
        "commits": final_commits
    }

    # Save the final result to the memory cache for 1 hour (3600 seconds)
    cache.set(cache_key, result, timeout=3600)

    return result



def analyze_team_contributions(team, commits_data):
    """
    Maps raw GitHub commits to registered TeamMembers and calculates summary stats.
    """
    # 1. Fetch all students actually assigned to this team in the database
    members = TeamMember.objects.filter(team=team).select_related('user')

    # 2. Build a fast lookup dictionary using github_username as the key
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

    # Pre-fill the dictionary for every team member
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
        if commit.get('is_merge'):
            continue
        gh_username = commit.get('author_username')

        if gh_username and gh_username.lower() in member_lookup:
            matched_member = member_lookup[gh_username.lower()]
            student_data = summary['mapped_students'][matched_member.user.pk]

            student_data['commit_count'] += 1
            student_data['total_additions'] += commit.get('additions', 0)
            student_data['total_deletions'] += commit.get('deletions', 0)
            student_data['commits'].append(commit)
        else:
            summary['unmapped_commits'].append(commit)

    # 5. Build Timeline Chart Data
    timeline_dict = defaultdict(int)
    for commit in commits_data:
        day_str = commit.get('date', '')[:10]
        if day_str:
            timeline_dict[day_str] += 1

    sorted_dates = sorted(timeline_dict.keys())
    summary['chart_labels'] = sorted_dates
    summary['chart_data'] = [timeline_dict[d] for d in sorted_dates]

    # 6. Integrity Flags Engine
    for pk, student in summary['mapped_students'].items():
        student['flags'] = []
        fluff_count = 0
        dump_count = 0
        burst_count = 0

        student_commits = sorted(student['commits'], key=lambda x: x['date'])

        for i, commit in enumerate(student_commits):
            total_changes = commit.get('additions', 0) + commit.get('deletions', 0)
            msg = commit.get('message', '').strip()

            if total_changes < 3 or len(msg) < 5:
                fluff_count += 1

            if commit.get('additions', 0) > 1000:
                dump_count += 1

            if i > 0:
                date_format = "%Y-%m-%dT%H:%M:%SZ"
                try:
                    current_date = datetime.strptime(commit['date'], date_format)
                    prev_date = datetime.strptime(student_commits[i - 1]['date'], date_format)

                    if (current_date - prev_date).total_seconds() < 120:
                        burst_count += 1
                except ValueError:
                    pass

        if fluff_count > 0:
            student['flags'].append(f"{fluff_count} trivial/fluff commits (Very low LOC or short messages).")
        if dump_count > 0:
            student['flags'].append(f"{dump_count} massive code dumps (>1,000 additions in a single commit).")
        if burst_count > 0:
            student['flags'].append(f"{burst_count} rapid-fire bursts (Commits pushed within 2 minutes of each other).")

    # 7. NEW: Calculate Fair Impact Score & Percentages for Progress Bars
    total_team_impact = 0
    for pk, student in summary['mapped_students'].items():
        impact = student['total_additions'] + student['total_deletions'] + student['commit_count']

        if impact == 0 and student['commit_count'] > 0:
            impact = student['commit_count']

        student['impact_score'] = impact
        total_team_impact += impact

    for pk, student in summary['mapped_students'].items():
        if total_team_impact > 0:
            student['percentage'] = round((student['impact_score'] / total_team_impact) * 100)
        else:
            student['percentage'] = 0

    return summary


def calculate_project_contribution_scores(project, force_refresh=False, target_team=None):
    """
    Retrieves and normalizes GitHub, Non-Coding Deliverable, and Peer Evaluation
    evidence for eligible team members. If `target_team` is provided, only
    calculates scores for that specific team for instant loading.
    """
    teams = [target_team] if target_team else list(project.teams.all())
    team_ids = [t.pk for t in teams]

    # 1. Batch Prefetch All Team Members
    all_members = TeamMember.objects.filter(team_id__in=team_ids).select_related('user', 'team')
    members_by_team = defaultdict(list)
    for tm in all_members:
        members_by_team[tm.team_id].append(tm)

    # 2. Batch Prefetch Verified Deliverable Contributions
    verified_delivs = DeliverableContribution.objects.filter(
        deliverable__team_id__in=team_ids,
        status='VERIFIED'
    ).select_related('deliverable')

    team_verified_deliv_count = defaultdict(int)
    student_verified_deliv_count = defaultdict(lambda: defaultdict(int))
    for dc in verified_delivs:
        t_id = dc.deliverable.team_id
        team_verified_deliv_count[t_id] += 1
        student_verified_deliv_count[t_id][dc.student_id] += 1

    # 3. Batch Prefetch Peer Evaluation Scores
    peer_scores = PeerEvaluationScore.objects.filter(
        evaluation__team_id__in=team_ids
    ).select_related('evaluation', 'criterion')

    student_peer_earned = defaultdict(lambda: defaultdict(float))
    student_peer_max = defaultdict(lambda: defaultdict(float))
    student_peer_review_ids = defaultdict(lambda: defaultdict(set))

    for ps in peer_scores:
        t_id = ps.evaluation.team_id
        eval_student_id = ps.evaluation.evaluatee_id
        student_peer_earned[t_id][eval_student_id] += ps.score
        student_peer_max[t_id][eval_student_id] += ps.criterion.max_score
        student_peer_review_ids[t_id][eval_student_id].add(ps.evaluation_id)

    # Configured Project Weights
    w_gh = float(project.weight_github or 0)
    w_deliv = float(project.weight_deliverables or 0)
    w_peer = float(project.weight_peer or 0)

    master_data = []
    project_total_commits = 0
    teams_with_repos = 0

    # 4. Evaluate Each Team and Member
    for team in teams:
        t_id = team.pk
        members = members_by_team.get(t_id, [])
        num_members = len(members)
        if num_members == 0:
            continue

        # --- A. GitHub Evidence Retrieval ---
        gh_available = False
        gh_analytics = None
        if team.github_repo_url:
            teams_with_repos += 1
            fetch_result = fetch_team_commits(team, force_refresh=force_refresh)
            if fetch_result.get('status') == 'success':
                gh_available = True
                gh_analytics = analyze_team_contributions(team, fetch_result['commits'])
                project_total_commits += gh_analytics['total_commits']

        total_team_impact = 0
        if gh_available and gh_analytics:
            for s_data in gh_analytics['mapped_students'].values():
                total_team_impact += s_data.get('impact_score', 0)

        expected_gh_impact = (total_team_impact / num_members) if num_members > 0 else 0

        # --- B. Deliverables Evidence Check ---
        total_team_delivs = team_verified_deliv_count[t_id]
        deliv_available = total_team_delivs > 0
        expected_delivs = (total_team_delivs / num_members) if num_members > 0 else 0

        # --- C. Calculate Individual Scores per Student ---
        for tm in members:
            student = tm.user
            s_id = student.pk
            evidence_notes = []

            # 1. Normalize GitHub Score (0 - 100)
            s_gh_data = gh_analytics['mapped_students'].get(s_id, {}) if (gh_available and gh_analytics) else {}
            commit_count = s_gh_data.get('commit_count', 0)
            additions = s_gh_data.get('total_additions', 0)
            deletions = s_gh_data.get('total_deletions', 0)
            flags = list(s_gh_data.get('flags', []))
            impact_score = s_gh_data.get('impact_score', 0)

            if not team.github_repo_url:
                gh_active = False
                gh_score = None
                evidence_notes.append("No Team Repo")
            elif not gh_available:
                gh_active = False
                gh_score = None
                evidence_notes.append("GitHub Sync Unavailable")
            elif total_team_impact == 0:
                gh_active = False
                gh_score = None
                evidence_notes.append("Zero Team Commits")
            else:
                gh_active = True
                if impact_score == 0:
                    gh_score = 0.0
                    evidence_notes.append("0 Commits")
                else:
                    raw_gh = (impact_score / expected_gh_impact) * 80.0 if expected_gh_impact > 0 else 0.0
                    gh_score = round(min(100.0, raw_gh), 1)

            # 2. Normalize Deliverables Score (0 - 100)
            s_deliv_count = student_verified_deliv_count[t_id][s_id]
            if not deliv_available:
                deliv_active = False
                deliv_score = None
                evidence_notes.append("No Verified Deliverables")
            else:
                deliv_active = True
                if s_deliv_count == 0:
                    deliv_score = 0.0
                    evidence_notes.append("0 Verified Deliverables")
                else:
                    raw_deliv = (s_deliv_count / expected_delivs) * 80.0 if expected_delivs > 0 else 0.0
                    deliv_score = round(min(100.0, raw_deliv), 1)

            # 3. Normalize Peer Evaluation Score (0 - 100)
            p_earned = student_peer_earned[t_id][s_id]
            p_max = student_peer_max[t_id][s_id]
            p_reviews_count = len(student_peer_review_ids[t_id][s_id])

            if p_max == 0:
                peer_active = False
                peer_score = None
                evidence_notes.append("No Peer Reviews")
            else:
                peer_active = True
                peer_score = round(min(100.0, (p_earned / p_max) * 100.0), 1)

            # 4. Dynamic Weight Redistribution & Final Score Calculation
            active_weight_sum = 0.0
            weighted_sum = 0.0

            if gh_active and w_gh > 0:
                active_weight_sum += w_gh
                weighted_sum += gh_score * w_gh

            if deliv_active and w_deliv > 0:
                active_weight_sum += w_deliv
                weighted_sum += deliv_score * w_deliv

            if peer_active and w_peer > 0:
                active_weight_sum += w_peer
                weighted_sum += peer_score * w_peer

            if active_weight_sum > 0:
                final_score = round(weighted_sum / active_weight_sum, 1)
                is_redistributed = active_weight_sum < 100.0

                # Calculate exact weighted points contributed to the 100-point total
                pts_gh = round((gh_score * w_gh) / active_weight_sum, 1) if (gh_active and w_gh > 0) else 0.0
                pts_deliv = round((deliv_score * w_deliv) / active_weight_sum, 1) if (
                            deliv_active and w_deliv > 0) else 0.0
                pts_peer = round((peer_score * w_peer) / active_weight_sum, 1) if (peer_active and w_peer > 0) else 0.0
            else:
                final_score = 0.0
                is_redistributed = False
                pts_gh = pts_deliv = pts_peer = 0.0
                evidence_notes = ["Awaiting Evidence"]

            master_data.append({
                'student_id': s_id,
                'name': student.name,
                'team_name': team.team_name,
                'github_username': student.github_username,
                'role': tm.role_in_team,
                'commit_count': commit_count,
                'total_additions': additions,
                'total_deletions': deletions,
                'verified_deliverables': s_deliv_count,
                'peer_reviews_count': p_reviews_count,
                'github_score': gh_score,
                'deliverables_score': deliv_score,
                'peer_score': peer_score,
                'pts_github': pts_gh,
                'pts_deliverables': pts_deliv,
                'pts_peer': pts_peer,
                'final_score': final_score,
                'is_redistributed': is_redistributed,
                'evidence_notes': evidence_notes,
                'flags': flags,
            })

    master_data.sort(key=lambda x: (x['final_score'], x['commit_count']), reverse=True)

    return {
        'master_data': master_data,
        'total_teams': len(teams),
        'teams_with_repos': teams_with_repos,
        'project_total_commits': project_total_commits,
    }