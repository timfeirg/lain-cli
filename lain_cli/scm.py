import re
from os import getcwd as cwd

import gitlab

from lain_cli.utils import error, must_get_env, tell_cluster_config

CWD = cwd()
REVIEWER_GEX = re.compile(r'(review|reviewer|reviewers):(.+)', flags=re.IGNORECASE)


def parse_reviewers(s):
    """
    >>> messages = '''
    ... review: a
    ... reviewers: b
    ... reviewer: c
    ... Reviewer:d,e
    ... Reviewer:f g
    ... Reviewer:@h @i j;k,l
    ... '''
    >>> rvs = parse_reviewers(messages)
    >>> sorted(list(rvs))
    ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l']
    """
    reviewers = set()
    for _, rvs in re.findall(REVIEWER_GEX, s):
        reviewers.update(re.split(',|@|;| ', rvs.strip()))

    reviewers.discard('')
    return reviewers


def tell_scm():
    cc = tell_cluster_config()
    endpoint = cc.get('gitlab')
    if not endpoint:
        error('gitlab not configured in cluster config', exit=1)

    token = must_get_env(
        'GITLAB_API_TOKEN',
        f'get your own token at {endpoint}/-/profile/personal_access_tokens',
    )
    return GitLabSCM(endpoint, token)


class GitLabSCM:
    def __init__(self, endpoint, token):
        self.endpoint = endpoint.rstrip('/')
        self.gl = gitlab.Gitlab(self.endpoint, private_token=token)

    def pending_reviewers(self, project, mr_id):
        pj = self.gl.projects.get(project)
        mr = pj.mergerequests.get(mr_id)
        mr_texts = mr.description
        mrc = mr.commits()
        for c in mrc:
            mr_texts += f'\n{c.message}'

        needed = parse_reviewers(mr_texts)
        approvals = mr.approvals.get()
        for dic in approvals.approved_by:
            user = dic['user']
            needed.discard(user['name'])
            needed.discard(user['username'])

        return needed, mr.web_url
