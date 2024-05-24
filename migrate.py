#!python

import argparse
import json
import re
import urllib.parse

import requests


parser = argparse.ArgumentParser(__name__)

parser.add_argument('--github-org', dest='github_org', required=True)
parser.add_argument('--github-repo', dest='github_repo', required=True)
parser.add_argument('--github-issue', dest='github_issue', required=True)
parser.add_argument('--github-token', dest='github_token', required=True)

parser.add_argument('--gitlab-project', dest='gitlab_project', required=True)
parser.add_argument('--gitlab-token', dest='gitlab_token', required=True)
parser.add_argument('--gitlab-domain', dest='gitlab_domain', required=False, default='gitlab.com')

args = parser.parse_args()

GITHUB_BASE_ISSUE_API_URL = f"https://api.github.com/repos/{args.github_org}/{args.github_repo}/issues/{args.github_issue}"
GITLAB_BASE_ISSUE_API_URL = f"https://{args.gitlab_domain}/api/v4/projects/{urllib.parse.quote_plus(args.gitlab_project)}/issues"

GITHUB_AUTH_HEADERS = {
    "Authorization": f"Bearer {args.github_token}",
    "X-GitHub-Api-Version": "2022-11-28",
    "Accept": "application/vnd.github+json",
}
GITLAB_AUTH_HEADERS = {
    "Authorization": f"Bearer {args.gitlab_token}",
}


# Step 1 - Get github issue details
github_issue_details = requests.get(GITHUB_BASE_ISSUE_API_URL, headers=GITHUB_AUTH_HEADERS).json()
print(f"Found github issue details: {github_issue_details.get('title')}")

# Step 2 - Get all github comments
github_comments = []
github_comments_itx = 1
github_comments_per_page = 100
while True:
    github_comments_page = requests.get(
        GITHUB_BASE_ISSUE_API_URL + f"/comments?page={github_comments_itx}&per_page={github_comments_per_page}",
        headers=GITHUB_AUTH_HEADERS
    ).json()
    github_comments += github_comments_page
    if len(github_comments_page) < github_comments_per_page:
        break
    github_comments_itx += 1

print(f"Found {len(github_comments)} github issue comments")

# Step 3 - Search for github comment referencing gitlab issue sync
gitlab_issue_re = re.compile(r"gitlab\-issue\-id\:(\d+)")
gitlab_issue_id = None
gitlab_cross_post_comment_id = None
for comment in github_comments:
    for comment_line in comment.get("body", "").split("\n"):
        if match := gitlab_issue_re.match(comment_line):
            gitlab_issue_id = match.group(1)
            gitlab_cross_post_comment_id = comment.get("id")
            print(f'Found gitlab issue from Github comment: {gitlab_issue_id}')
            break

# Step 4 - (if not already created), create gitlab issue
if not gitlab_issue_id:
    print("Could not find gitlab issue - creating new issue")
    gitlab_create_issue_res = requests.post(GITLAB_BASE_ISSUE_API_URL,
        headers=GITLAB_AUTH_HEADERS,
        json={
            "title": github_issue_details.get("title"),
            "description": (
                (github_issue_details.get("body") or "").replace("\r\n", "\n") +
                f"\n\nGithub reference: {github_issue_details.get('html_url')}"
            )
        }
    ).json()
    gitlab_issue_id = gitlab_create_issue_res.get("iid")
    print(f'Created new gitlab issue: {gitlab_issue_id}')

    # Post comment to github issue with gitlab issue ID
    github_comment_post = requests.post(
        GITHUB_BASE_ISSUE_API_URL + "/comments",
        headers=GITHUB_AUTH_HEADERS,
        json={"body": f"Created gitlab issue: {gitlab_create_issue_res.get('web_url')}\ngitlab-issue-id:{gitlab_issue_id}"}
    )
    if github_comment_post.status_code != 201:
        raise Exception(f"Could not post comment to Github issue: {github_comment_post.status_code}: {github_comment_post.json()}")
    gitlab_cross_post_comment_id = github_comment_post.json().get("id")
    print('Posted comment on Github issue')

# Step 5 - (if already exist), check comments that already exist in gitlab
gitlab_comments = []
gitlab_comment_itx = 1
gitlab_comments_per_page = 100
while True:
    gitlab_comments_page = requests.get(
        GITLAB_BASE_ISSUE_API_URL + f"/{gitlab_issue_id}/notes?page={gitlab_comment_itx}&per_page={gitlab_comments_per_page}",
        headers=GITLAB_AUTH_HEADERS
    ).json()
    gitlab_comments += gitlab_comments_page
    if len(gitlab_comments_page) < gitlab_comments_per_page:
        break
    gitlab_comment_itx += 1

# Map of gitlab comments, keyed by github issue ID and value of gitlab comment body and gitlab note ID
cross_post_gitlab_comments = {}
gitlab_comment_re = re.compile(r"github-comment-id:(\d+)")
for comment in gitlab_comments:
    for comment_line in comment.get("body", "").split("\n"):
        if match := gitlab_comment_re.match(comment_line):
            cross_post_gitlab_comments[match.group(1)] = {
                "body": comment.get("body"),
                "note_id": comment.get("id")
            }

print(f"Comment IDs already found: {cross_post_gitlab_comments.keys()}")

def get_gitlab_comment_body(github_issue_details):
    return (
        f"From @{github_issue_details.get('user', {}).get('login', '')}\n\n" +
        github_issue_details.get("body") +
        f"\n\nLink: {github_issue_details.get('html_url')}" +
        f"\n\ngithub-comment-id:{github_issue_details.get('id')}"
    )

# Step 6 - iterate through comments, cross-posting any that don't exist
for github_comment in github_comments:
    github_comment_id = str(github_comment.get("id"))
    if github_comment_id == str(gitlab_cross_post_comment_id):
        print("Skipping cross-post comment")
        continue

    gitlab_comment_body = get_gitlab_comment_body(github_comment)
    if github_comment_id not in cross_post_gitlab_comments.keys():
        print(f"Posting comment: {github_comment_id}")
        gitlab_comment_post_res = requests.post(
            GITLAB_BASE_ISSUE_API_URL + f"/{gitlab_issue_id}/notes",
            headers=GITLAB_AUTH_HEADERS,
            json={
                "body": gitlab_comment_body
            }
        )
        if gitlab_comment_post_res.status_code != 201:
            raise Exception(f"Unable to post comment on gitlab: {gitlab_comment_post_res.status_code}: {gitlab_comment_post_res.json()}")
    elif (cross_post_gitlab_comments[github_comment_id]["body"] or "").replace('\r', '') != gitlab_comment_body.replace('\r', ''):
        print(f"Github comment for {github_comment_id} has been updated - updating gitlab comment")
        gitlab_comment_update_res = requests.put(
            GITLAB_BASE_ISSUE_API_URL + f"/{gitlab_issue_id}/notes/{cross_post_gitlab_comments[github_comment_id]['note_id']}",
            headers=GITLAB_AUTH_HEADERS,
            json={
                "body": gitlab_comment_body
            }
        )
    else:
        print(f"Github comment for {github_comment_id} is up-to-date")
