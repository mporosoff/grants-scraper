"""Read all review surfaces for one immutable generated PR; never request duplicates."""
import json
from datetime import datetime
import re
import subprocess
import time

BOT = 'chatgpt-codex-connector[bot]'


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path], text=True, timeout=45))


def all_pages(path):
    result = []
    for page in range(1, 101):
        rows = api(f'{path}?per_page=100&page={page}')
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise ValueError('Review evidence pagination was not complete')


def all_threads(repository, number):
    owner, name = repository.split('/')
    query = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
      repository(owner:$owner,name:$name) { pullRequest(number:$number) {
        reviewThreads(first:100,after:$cursor) { pageInfo {hasNextPage endCursor}
          nodes { isResolved comments(first:100) { pageInfo {hasNextPage}
            nodes { body author {login} originalCommit {oid} } } }
        } } } }'''
    cursor, result = None, []
    while True:
        args = ['gh', 'api', 'graphql', '-f', f'query={query}', '-f', f'owner={owner}', '-f', f'name={name}', '-F', f'number={number}']
        if cursor:
            args += ['-f', f'cursor={cursor}']
        response = json.loads(subprocess.check_output(args, text=True, timeout=45))
        if response.get('errors'):
            raise ValueError('Review thread evidence is unavailable')
        page = response['data']['repository']['pullRequest']['reviewThreads']
        if any(thread['comments']['pageInfo']['hasNextPage'] for thread in page['nodes']):
            raise ValueError('Review thread exceeds bounded evidence reader; inspect before publication')
        result.extend(page['nodes'])
        if not page['pageInfo']['hasNextPage']:
            return result
        cursor = page['pageInfo']['endCursor']


def request_boundary(pr, comments, head):
    requests = [re.search(r'Review boundary: ([^\s]+)', row.get('body', '')).group(1)
                if re.search(r'Review boundary: ([^\s]+)', row.get('body', '')) else row['created_at'] for row in comments
                if f'<!-- funding-finder-review:{head} -->' in row.get('body', '')
                and row.get('user', {}).get('login') == pr.get('user', {}).get('login')]
    if requests:
        return max(requests, key=parsed_time)
    if f'Review head: `{head}`' in pr.get('body', ''):
        return pr['created_at']
    # An exact-head submitted review remains acceptable. A reaction without a
    # verifiable request boundary must never approve a different, rebased head.
    return '9999-12-31T23:59:59Z'


def parsed_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def reviewed_head(repository, body, head):
    match = re.search(r'Reviewed commit:?\*{0,2}:?\s*`?([a-f0-9]{10,40})\b', body)
    if not match or not head.startswith(match[1]):
        return False
    if match[1] == head:
        return True
    # GitHub's terminal bot comment uses ten characters. Resolve that prefix
    # through authenticated repository metadata; a textual prefix alone is not
    # exact-head evidence and an ambiguous/unavailable resolution fails closed.
    return api(f'repos/{repository}/commits/{match[1]}').get('sha') == head


def review_state(repository, number, head, created_at=None):
    pr = api(f'repos/{repository}/pulls/{number}')
    if pr['head']['sha'] != head or pr['base']['ref'] != 'main':
        raise ValueError('Generated PR changed during exact-head review')
    comments = all_pages(f'repos/{repository}/issues/{number}/comments')
    created_at = created_at or request_boundary(pr, comments, head)
    reviews = all_pages(f'repos/{repository}/pulls/{number}/reviews')
    inline = all_pages(f'repos/{repository}/pulls/{number}/comments')
    reactions = all_pages(f'repos/{repository}/issues/{number}/reactions')
    threads = all_threads(repository, number)
    bot = lambda row: row.get('user', {}).get('login') == BOT
    terminal_reviews = [row for row in reviews if bot(row) and row.get('commit_id') == head and row.get('state') in ('APPROVED', 'COMMENTED', 'CHANGES_REQUESTED')]
    terminal_comments = [row for row in comments if bot(row) and 'Codex Review' in row.get('body', '')
                         and reviewed_head(repository, row.get('body', ''), head)]
    clean_reaction = any(bot(row) and row.get('content') == '+1' and parsed_time(row['created_at']) >= parsed_time(created_at) for row in reactions)
    completed = bool(terminal_reviews or terminal_comments or clean_reaction)
    findings = [row for thread in threads if not thread['isResolved'] for row in thread['comments']['nodes']
                if (row.get('originalCommit') or {}).get('oid') == head
                and (row.get('author') or {}).get('login', '').removesuffix('[bot]') == BOT.removesuffix('[bot]')
                and re.search(r'\bP[012]\b', row.get('body', ''))]
    findings += [row for row in terminal_reviews + terminal_comments
                 if row.get('state') == 'CHANGES_REQUESTED' or re.search(r'\bP[012]\b', row.get('body', ''))]
    return completed, findings


def wait_for_review(repository, number, head, *, timeout=1800, interval=30):
    deadline = time.monotonic() + timeout
    errors = 0
    while time.monotonic() < deadline:
        try:
            completed, findings = review_state(repository, number, head)
        except (OSError, subprocess.SubprocessError):
            errors += 1
            if errors >= 3:
                raise RuntimeError('Review service unavailable after bounded retries') from None
        else:
            errors = 0
            if completed:
                if findings:
                    raise ValueError('Terminal generated-candidate review has findings; retain candidate and consolidate the PR findings')
                return
        print(f'Awaiting terminal exact-head review of PR #{number} ({head})', flush=True)
        time.sleep(interval)
    raise ValueError('Review remains pending; preserve candidate and continue the same review without regeneration or duplicate requests')
