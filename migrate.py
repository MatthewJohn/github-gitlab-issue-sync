#!python

import argparse

from migration_lib import Migration

parser = argparse.ArgumentParser(__name__)

parser.add_argument('--github-org', dest='github_org', required=True)
parser.add_argument('--github-repo', dest='github_repo', required=True)
parser.add_argument('--github-issue', dest='github_issue', required=True)
parser.add_argument('--github-token', dest='github_token', required=True)

parser.add_argument('--gitlab-project', dest='gitlab_project', required=True)
parser.add_argument('--gitlab-token', dest='gitlab_token', required=True)
parser.add_argument('--gitlab-domain', dest='gitlab_domain', required=False, default='gitlab.com')

args = parser.parse_args()

migration = Migration(
    github_org=args.github_org,
    github_repo=args.github_repo,
    gitlab_domain=args.gitlab_domain,
    gitlab_project=args.gitlab_project,
    github_token=args.github_token,
    gitlab_token=args.gitlab_token
)

migration.sync_github_issue(github_issue=args.github_issue)
