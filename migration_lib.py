
import json
import re
import urllib.parse

import requests

class Migration:

    def __init__(self, github_org, github_repo, gitlab_domain, gitlab_project, github_token, gitlab_token):
        """Store member variables"""
        self._github_org = github_org
        self._github_repo = github_repo
        self._github_token = github_token

        self._gitlab_domain = gitlab_domain
        self._gitlab_project = gitlab_project
        self._gitlab_token = gitlab_token

        for i in ["github_org", "github_repo", "github_token", "gitlab_domain",
                  "gitlab_project", "gitlab_token"]:
            if not getattr(self, f"_{i}"):
                raise Exception(f"{i} must be provided as arg or env variable {i.upper()}")

    @property
    def github_headers(self):
        """return headers for github"""
        return {
            "Authorization": f"Bearer {self._github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Accept": "application/vnd.github+json",
        }

    def get_github_issues(self):
        """Return all github issues"""
        github_issues = []
        page = 1
        issues_per_page = 50
        while True:
            res = requests.get(
                f"https://api.github.com/repos/{self._github_org}/{self._github_repo}/issues?per_page={issues_per_page}&page={page}"
            )
            if res.status_code != 200:
                raise Exception("Got non-200 whilst getting issues")
            page_issues = res.json()

            github_issues += [
                i["number"] for i in page_issues
                if i.get("html_url", "").endswith(f"/issues/{i.get('number')}")
            ]
            if len(page_issues) < issues_per_page:
                break
            page += 1

        return github_issues

    def sync_github_issue(self, github_issue):
        """Perform sync of github issue to Gitlab"""
        github_base_issue_api_url = f"https://api.github.com/repos/{self._github_org}/{self._github_repo}/issues/{github_issue}"
        gitlab_base_issue_api_url = f"https://{self._gitlab_domain}/api/v4/projects/{urllib.parse.quote_plus(self._gitlab_project)}/issues"

        gitlab_headers = {
            "Authorization": f"Bearer {self._gitlab_token}",
        }

        # Step 1 - Get github issue details
        github_issue_details = requests.get(github_base_issue_api_url, headers=self.github_headers).json()
        print(f"Found github issue details: {github_issue_details.get('title')}")

        # Step 2 - Get all github comments
        github_comments = []
        github_comments_itx = 1
        github_comments_per_page = 100
        while True:
            github_comments_page = requests.get(
                github_base_issue_api_url + f"/comments?page={github_comments_itx}&per_page={github_comments_per_page}",
                headers=self.github_headers
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
            gitlab_create_issue_res = requests.post(gitlab_base_issue_api_url,
                headers=gitlab_headers,
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
            if gitlab_issue_id is None:
                raise Exception(f"Failed to create github issue: {gitlab_create_issue_res}")

            # Post comment to github issue with gitlab issue ID
            github_comment_post = requests.post(
                github_base_issue_api_url + "/comments",
                headers=self.github_headers,
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
                gitlab_base_issue_api_url + f"/{gitlab_issue_id}/notes?page={gitlab_comment_itx}&per_page={gitlab_comments_per_page}",
                headers=gitlab_headers
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
                    gitlab_base_issue_api_url + f"/{gitlab_issue_id}/notes",
                    headers=gitlab_headers,
                    json={
                        "body": gitlab_comment_body
                    }
                )
                if gitlab_comment_post_res.status_code != 201:
                    raise Exception(f"Unable to post comment on gitlab: {gitlab_comment_post_res.status_code}: {gitlab_comment_post_res.json()}")
            elif (cross_post_gitlab_comments[github_comment_id]["body"] or "").replace('\r', '') != gitlab_comment_body.replace('\r', ''):
                print(f"Github comment for {github_comment_id} has been updated - updating gitlab comment")
                gitlab_comment_update_res = requests.put(
                    gitlab_base_issue_api_url + f"/{gitlab_issue_id}/notes/{cross_post_gitlab_comments[github_comment_id]['note_id']}",
                    headers=gitlab_headers,
                    json={
                        "body": gitlab_comment_body
                    }
                )
            else:
                print(f"Github comment for {github_comment_id} is up-to-date")
