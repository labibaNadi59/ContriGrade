import requests
from django.conf import settings
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from django.core.cache import cache
from .models import TeamMember, DeliverableContribution, PeerEvaluationScore
import time

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
    """Worker function to fetch LOC stats for a single commit with permanent SHA caching."""
    sha = commit_info['sha']
    sha_cache_key = f"gh_commit_stats_{owner}_{repo}_{sha}"
    cached_stats = cache.get(sha_cache_key)

    if cached_stats is not None:
        commit_info['additions'] = cached_stats.get('additions', 0)
        commit_info['deletions'] = cached_stats.get('deletions', 0)
        return commit_info

    deep_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"

    try:
        resp = requests.get(deep_url, headers=headers, timeout=6)
        if resp.status_code == 200:
            stats = resp.json().get('stats', {})
            additions = stats.get('additions', 0)
            deletions = stats.get('deletions', 0)
            commit_info['additions'] = additions
            commit_info['deletions'] = deletions
            # Commit SHAs are immutable, cache their LOC stats for 7 days
            cache.set(sha_cache_key, {'additions': additions, 'deletions': deletions}, timeout=604800)
        else:
            commit_info['additions'] = 0
            commit_info['deletions'] = 0
    except requests.RequestException:
        commit_info['additions'] = 0
        commit_info['deletions'] = 0

    return commit_info


def fetch_team_commits(team, force_refresh=False):
    if not team.github_repo_url:
        return {"status": "error", "message": "No repository linked to this team."}

    cache_key = f"team_{team.pk}_github_commits"

    if not force_refresh:
        cached_data = cache.get(cache_key)
        if cached_data:
            return cached_data

    clean_url = team.github_repo_url.strip().rstrip('/')
    if clean_url.endswith('.git'):
        clean_url = clean_url[:-4]

    pattern = r'^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)$'
    match = re.match(pattern, clean_url)

    if not match:
        return {"status": "error", "message": "Invalid repository URL format."}

    owner, repo = match.groups()
    token = getattr(settings, 'GITHUB_API_TOKEN', None)

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Cache-Control": "no-cache, no-store, must-revalidate"
    }
    if token:
        headers["Authorization"] = f"token {token}"

    current_timestamp = int(time.time())
    branches_url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100&t={current_timestamp}"
    branch_names = []

    try:
        branches_res = requests.get(branches_url, headers=headers, timeout=6)
        if branches_res.status_code == 200 and isinstance(branches_res.json(), list):
            branch_names = [b['name'] for b in branches_res.json() if 'name' in b]
    except requests.RequestException:
        pass

    total_branches = len(branch_names) if branch_names else 1

    # --- THE CRITICAL FIX ---
    # Force 'main' and 'master' to always be checked FIRST, regardless of alphabetical order
    if branch_names:
        branch_names = sorted(branch_names, key=lambda x: 0 if x in ['main', 'master'] else 1)

    unique_raw_commits = {}

    try:
        if branch_names:
            # Check up to 8 branches now that main is guaranteed to be first
            for branch in branch_names[:8]:
                api_url = f"https://api.github.com/repos/{owner}/{repo}/commits"
                response = requests.get(
                    api_url,
                    headers=headers,
                    params={'sha': branch, 'per_page': 100, 't': current_timestamp},
                    timeout=10
                )
                if response.status_code == 200 and isinstance(response.json(), list):
                    for item in response.json():
                        unique_raw_commits[item['sha']] = item
        else:
            api_url = f"https://api.github.com/repos/{owner}/{repo}/commits"
            response = requests.get(
                api_url,
                headers=headers,
                params={'per_page': 100, 't': current_timestamp},
                timeout=10
            )
            if response.status_code == 200 and isinstance(response.json(), list):
                for item in response.json():
                    unique_raw_commits[item['sha']] = item
    except requests.RequestException as e:
        return {"status": "error", "message": f"Network error: {str(e)}"}

    base_commits = []
    for sha, item in unique_raw_commits.items():
        is_merge = len(item.get('parents', [])) > 1
        github_account = item.get('author') or item.get('committer')
        commit_author_obj = item.get('commit', {}).get('author', {})

        author_login = github_account.get('login') if isinstance(github_account, dict) else None
        if author_login == 'web-flow' and not item.get('author'):
            author_login = None

        base_commits.append({
            'sha': sha,
            'author_username': author_login,
            'author_name': commit_author_obj.get('name', 'Unknown Author'),
            'author_email': commit_author_obj.get('email', ''),
            'message': item.get('commit', {}).get('message', ''),
            'date': commit_author_obj.get('date', ''),
            'url': item.get('html_url', ''),
            'is_merge': is_merge
        })

    normal_commits = [c for c in base_commits if not c['is_merge']]
    merge_commits = [c for c in base_commits if c['is_merge']]

    final_commits = []

    try:
        from .utils import fetch_deep_commit_stats  # Adjust this import based on your file structure
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_commit = {
                executor.submit(fetch_deep_commit_stats, commit, owner, repo, headers): commit
                for commit in normal_commits
            }
            for future in as_completed(future_to_commit):
                final_commits.append(future.result())
    except ImportError:
        for c in normal_commits:
            c['additions'] = 0
            c['deletions'] = 0
            final_commits.append(c)

    for mc in merge_commits:
        mc['additions'] = 0
        mc['deletions'] = 0
        final_commits.append(mc)

    # Sort final output by date descending
    final_commits.sort(key=lambda x: x['date'], reverse=True)

    result = {
        "status": "success",
        "total_commits": len(final_commits),
        "non_merge_commits": len(normal_commits),
        "total_branches": total_branches,
        "commits": final_commits
    }

    cache.set(cache_key, result, timeout=3600)
    return result


def analyze_team_contributions(team, commits_data):
    members = TeamMember.objects.filter(team=team).select_related('user')

    member_lookup = {}
    name_lookup = {}
    for member in members:
        if member.user.github_username:
            clean_gh = member.user.github_username.strip().lstrip('@').lower()
            member_lookup[clean_gh] = member
        if member.user.name:
            name_lookup[member.user.name.strip().lower()] = member
        if member.user.email:
            name_lookup[member.user.email.strip().lower()] = member

    non_merge_commits = [c for c in commits_data if not c.get('is_merge')]

    summary = {
        'mapped_students': {},
        'unmapped_commits': [],
        'total_commits': len(non_merge_commits),
        'raw_total_commits': len(commits_data),
        'merge_commits_count': len(commits_data) - len(non_merge_commits),
        'chart_labels': [],
        'chart_data': []
    }

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

    for commit in commits_data:
        gh_username = (commit.get('author_username') or '').strip().lstrip('@').lower()
        author_name = (commit.get('author_name') or '').strip().lower()
        author_email = (commit.get('author_email') or '').strip().lower()

        matched_member = None
        if gh_username and gh_username in member_lookup:
            matched_member = member_lookup[gh_username]
        elif author_name and author_name in name_lookup:
            matched_member = name_lookup[author_name]
        elif author_email and author_email in name_lookup:
            matched_member = name_lookup[author_email]
        elif author_name and author_name in member_lookup:
            matched_member = member_lookup[author_name]

        # NEW: Fuzzy Mapping fallback!
        # (e.g. if local git says "Labiba" but Django name is "Labiba Rahman Nadi")
        if not matched_member and author_name and len(author_name) > 2:
            for clean_name, member in name_lookup.items():
                if author_name in clean_name or clean_name in author_name:
                    matched_member = member
                    break

        if matched_member:
            commit['is_unmapped'] = False
            commit['mapped_student_name'] = matched_member.user.name
            if not commit.get('is_merge'):
                student_data = summary['mapped_students'][matched_member.user.pk]
                student_data['commit_count'] += 1
                student_data['total_additions'] += commit.get('additions', 0)
                student_data['total_deletions'] += commit.get('deletions', 0)
                student_data['commits'].append(commit)
        else:
            commit['is_unmapped'] = True
            summary['unmapped_commits'].append(commit)

    # (The rest of the function remains exactly the same...)
    timeline_dict = defaultdict(int)
    for commit in non_merge_commits:
        day_str = commit.get('date', '')[:10]
        if day_str:
            timeline_dict[day_str] += 1

    sorted_dates = sorted(timeline_dict.keys())
    summary['chart_labels'] = sorted_dates
    summary['chart_data'] = [timeline_dict[d] for d in sorted_dates]

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
            student['flags'].append(f"{fluff_count} trivial/fluff commits.")
        if dump_count > 0:
            student['flags'].append(f"{dump_count} massive code dumps.")
        if burst_count > 0:
            student['flags'].append(f"{burst_count} rapid-fire bursts.")

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


def detect_anomalies(
    flags=None,
    final_score=0.0,
    active_weight_sum=0.0,
    gh_active=False,
    commit_count=0,
    deliv_active=False,
    s_deliv_count=0,
    peer_active=False,
    gh_score=None,
    deliv_score=None,
    peer_score=None,
    w_gh=0.0,
    w_deliv=0.0,
    **kwargs
):
    """
    Evaluates individual contribution metrics against Cross-Pillar & GitHub anomaly rules:
      - Rule A: Promote existing GitHub commit pattern flags (fluff, bulk dump, burst, unusual).
      - Rule B: Free-Riding / Low Overall Participation (< 35% or 0 work output).
      - Rule C: Peer Evaluation vs. Objective Output Mismatch (>= 35% gap).
      - Rule D: Single-Pillar Siloing (Code-only or Docs-only with >= 80% and 0.0% in other).
    """
    flags = list(flags or [])
    anomalies = []

    # Rule A: Promote existing GitHub commit pattern flags with clear explanations
    for gh_flag in flags:
        if "trivial/fluff" in gh_flag:
            anomalies.append({
                'title': 'Trivial / Fluff Commit Pattern',
                'category': 'GitHub Integrity',
                'severity': 'warning',
                'explanation': f"{gh_flag} Triggered when commits contain fewer than 3 line changes or messages under 5 characters, which may artificially inflate commit counts."
            })
        elif "massive code dumps" in gh_flag:
            anomalies.append({
                'title': 'Bulk Code Dump Detected',
                'category': 'GitHub Integrity',
                'severity': 'high',
                'explanation': f"{gh_flag} Pushing over 1,000 lines in a single commit suggests bulk uploading or unreviewed code rather than iterative development."
            })
        elif "rapid-fire bursts" in gh_flag:
            anomalies.append({
                'title': 'Rapid-Fire Commit Burst',
                'category': 'GitHub Integrity',
                'severity': 'warning',
                'explanation': f"{gh_flag} Multiple commits pushed within 2 minutes of each other often indicate fragmented edits or automated script pushes."
            })
        else:
            anomalies.append({
                'title': 'Unusual GitHub Activity',
                'category': 'GitHub Integrity',
                'severity': 'warning',
                'explanation': gh_flag
            })

    # Rule B: Free-Riding / Low Overall Participation
    if active_weight_sum > 0 and final_score < 35.0:
        anomalies.append({
            'title': 'Low Overall Contribution (Potential Free-Riding)',
            'category': 'Participation',
            'severity': 'high',
            'explanation': f"Student's overall weighted score is {final_score}% (below the 35% threshold) while the team has active project evidence logged."
        })
    elif (gh_active and commit_count == 0) and (deliv_active and s_deliv_count == 0):
        anomalies.append({
            'title': 'Zero Recorded Work Output',
            'category': 'Participation',
            'severity': 'high',
            'explanation': "Student has 0 mapped GitHub commits and 0 verified deliverables despite active team submissions in both pillars."
        })

    # Rule C: Peer Evaluation vs. Objective Output Mismatch
    obj_scores = [s for s in [gh_score if gh_active else None, deliv_score if deliv_active else None] if s is not None]
    if peer_active and obj_scores and peer_score is not None:
        avg_obj_score = round(sum(obj_scores) / len(obj_scores), 1)
        if peer_score - avg_obj_score >= 35.0:
            anomalies.append({
                'title': 'Peer Rating Inflation (High Peer vs. Low Output)',
                'category': 'Cross-Pillar Mismatch',
                'severity': 'warning',
                'explanation': f"Student received a {peer_score}% peer evaluation score, which is {round(peer_score - avg_obj_score, 1)}% higher than their recorded objective average ({avg_obj_score}%)."
            })
        elif avg_obj_score - peer_score >= 35.0:
            anomalies.append({
                'title': 'Peer Rating Deficit (High Output vs. Low Peer Score)',
                'category': 'Cross-Pillar Mismatch',
                'severity': 'warning',
                'explanation': f"Student achieved a {avg_obj_score}% objective output average across code/tasks, but teammates rated them significantly lower ({peer_score}%)."
            })

    # Rule D: Single-Pillar Siloing (Code-Only or Docs-Only)
    if gh_active and deliv_active and w_gh > 0 and w_deliv > 0 and gh_score is not None and deliv_score is not None:
        if gh_score == 0.0 and deliv_score >= 80.0:
            anomalies.append({
                'title': 'Non-Coding Silo (Zero Code Contribution)',
                'category': 'Work Distribution',
                'severity': 'warning',
                'explanation': f"Student achieved {deliv_score}% in verified deliverables ({s_deliv_count} tasks) but contributed 0 commits to the team repository."
            })
        elif deliv_score == 0.0 and gh_score >= 80.0:
            anomalies.append({
                'title': 'Coding-Only Silo (Zero Non-Coding Tasks)',
                'category': 'Work Distribution',
                'severity': 'warning',
                'explanation': f"Student achieved {gh_score}% in GitHub code impact ({commit_count} commits) but has 0 verified non-coding deliverable tasks."
            })

    return anomalies


detect_student_anomalies = detect_anomalies


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
                pts_peer = round((peer_score * w_peer) / active_weight_sum, 1) if (
                        peer_active and w_peer > 0) else 0.0
            else:
                final_score = 0.0
                is_redistributed = False
                pts_gh = pts_deliv = pts_peer = 0.0
                evidence_notes = ["Awaiting Evidence"]

            # 5. Cross-Pillar & GitHub Anomaly Detection Engine
            anomalies = []

            # Rule A: Promote existing GitHub commit pattern flags with clear explanations
            for gh_flag in flags:
                if "trivial/fluff" in gh_flag:
                    anomalies.append({
                        'title': 'Trivial / Fluff Commit Pattern',
                        'category': 'GitHub Integrity',
                        'severity': 'warning',
                        'explanation': f"{gh_flag} Triggered when commits contain fewer than 3 line changes or messages under 5 characters, which may artificially inflate commit counts."
                    })
                elif "massive code dumps" in gh_flag:
                    anomalies.append({
                        'title': 'Bulk Code Dump Detected',
                        'category': 'GitHub Integrity',
                        'severity': 'high',
                        'explanation': f"{gh_flag} Pushing over 1,000 lines in a single commit suggests bulk uploading or unreviewed code rather than iterative development."
                    })
                elif "rapid-fire bursts" in gh_flag:
                    anomalies.append({
                        'title': 'Rapid-Fire Commit Burst',
                        'category': 'GitHub Integrity',
                        'severity': 'warning',
                        'explanation': f"{gh_flag} Multiple commits pushed within 2 minutes of each other often indicate fragmented edits or automated script pushes."
                    })
                else:
                    anomalies.append({
                        'title': 'Unusual GitHub Activity',
                        'category': 'GitHub Integrity',
                        'severity': 'warning',
                        'explanation': gh_flag
                    })

            # Rule B: Free-Riding / Low Overall Participation
            if active_weight_sum > 0 and final_score < 35.0:
                anomalies.append({
                    'title': 'Low Overall Contribution (Potential Free-Riding)',
                    'category': 'Participation',
                    'severity': 'high',
                    'explanation': f"Student's overall weighted score is {final_score}% (below the 35% threshold) while the team has active project evidence logged."
                })
            elif (gh_active and commit_count == 0) and (deliv_active and s_deliv_count == 0):
                anomalies.append({
                    'title': 'Zero Recorded Work Output',
                    'category': 'Participation',
                    'severity': 'high',
                    'explanation': "Student has 0 mapped GitHub commits and 0 verified deliverables despite active team submissions in both pillars."
                })

            # Rule C: Peer Evaluation vs. Objective Output Mismatch
            obj_scores = [s for s in [gh_score if gh_active else None, deliv_score if deliv_active else None] if s is not None]
            if peer_active and obj_scores:
                avg_obj_score = round(sum(obj_scores) / len(obj_scores), 1)
                if peer_score - avg_obj_score >= 35.0:
                    anomalies.append({
                        'title': 'Peer Rating Inflation (High Peer vs. Low Output)',
                        'category': 'Cross-Pillar Mismatch',
                        'severity': 'warning',
                        'explanation': f"Student received a {peer_score}% peer evaluation score, which is {round(peer_score - avg_obj_score, 1)}% higher than their recorded objective output average ({avg_obj_score}%)."
                    })
                elif avg_obj_score - peer_score >= 35.0:
                    anomalies.append({
                        'title': 'Peer Rating Deficit (High Output vs. Low Peer Score)',
                        'category': 'Cross-Pillar Mismatch',
                        'severity': 'warning',
                        'explanation': f"Student achieved a {avg_obj_score}% objective output average across code/tasks, but teammates rated them significantly lower ({peer_score}%)."
                    })

            # Rule D: Single-Pillar Siloing (Code-Only or Docs-Only)
            if gh_active and deliv_active and w_gh > 0 and w_deliv > 0:
                if gh_score == 0.0 and deliv_score >= 80.0:
                    anomalies.append({
                        'title': 'Non-Coding Silo (Zero Code Contribution)',
                        'category': 'Work Distribution',
                        'severity': 'warning',
                        'explanation': f"Student achieved {deliv_score}% in verified deliverables ({s_deliv_count} tasks) but contributed 0 commits to the team repository."
                    })
                elif deliv_score == 0.0 and gh_score >= 80.0:
                    anomalies.append({
                        'title': 'Coding-Only Silo (Zero Non-Coding Tasks)',
                        'category': 'Work Distribution',
                        'severity': 'warning',
                        'explanation': f"Student achieved {gh_score}% in GitHub code impact ({commit_count} commits) but has 0 verified non-coding deliverable tasks."
                    })

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
                'anomalies': anomalies,
                'anomaly_count': len(anomalies),
                'gh_impact_score': round(impact_score, 2) if gh_active else 0,
                'gh_expected_impact': round(expected_gh_impact, 2) if gh_active else 0,
                'deliv_student_count': s_deliv_count,
                'deliv_expected_count': round(expected_delivs, 2),
                'peer_earned': round(p_earned, 2),
                'peer_max': round(p_max, 2),
            })

    # Outside both the member loop and team loop
    master_data.sort(key=lambda x: (x['final_score'], x['commit_count']), reverse=True)

    return {
        'master_data': master_data,
        'total_teams': len(teams),
        'teams_with_repos': teams_with_repos,
        'project_total_commits': project_total_commits,
    }

