
import time
import os

from migration_lib import Migration

SLEEP_INTERVAL_MINS = 120

migration = Migration(
    github_org=os.environ.get("GITHUB_ORG"),
    github_repo=os.environ.get("GITHUB_REPO"),
    gitlab_domain=os.environ.get("GITLAB_DOMAIN"),
    gitlab_project=os.environ.get("GITLAB_PROJECT"),
    github_token=os.environ.get("GITHUB_TOKEN"),
    gitlab_token=os.environ.get("GITLAB_TOKEN")
)

while True:
    for github_issue in migration.get_gitub_issues():
        migration.sync_github_issue(github_issue)

    time.sleep(SLEEP_INTERVAL_MINS * 60)
