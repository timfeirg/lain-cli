from random import choices

import gitlab

from lain_cli.utils import error, must_get_env, tell_cluster_config, warn


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

    def is_approved(self, project_path, mr_id):
        pj = self.gl.projects.get(project_path)
        mr = pj.mergerequests.get(mr_id)
        approvals = mr.approvals.get()
        return approvals.approved

    @staticmethod
    def is_active(u):
        if not u:
            return False
        if u.get('state') != 'active':
            return False
        return True

    def assign_mr(self, project_path, mr_id):
        pj = self.gl.projects.get(project_path)
        mr = pj.mergerequests.get(mr_id)
        reviewers = mr.reviewers
        assignee = mr.assignee
        if reviewers or assignee:
            if self.is_active(reviewers[0]) and self.is_active(assignee):
                warn(f'already assigned to {assignee}, reviewer {reviewers}')
                return
        contributors = pj.repository_contributors()
        contributors_names = set()
        for c in contributors:
            contributors_names.add(c['name'])
            contributors_names.add(c['email'])

        author = mr.author
        author_names = {author['name'], author['username']}
        candidates = []

        def add_attr(s, model, attr):
            if hasattr(model, attr):
                s.add(getattr(model, attr))

        for user in pj.users.list(all=True):
            if user.state != 'active':
                continue
            user_names = set()
            user_names.add(user.name)
            user_names.add(user.username)
            add_attr(user_names, user, 'email')
            add_attr(user_names, user, 'commit_email')
            add_attr(user_names, user, 'public_email')
            if user_names.intersection(author_names):
                # author will not be his own reviewers
                continue
            if user_names.intersection(contributors_names):
                candidates.append(user)

        chosen = choices(candidates, k=2)
        # https://forge.extranet.logilab.fr/open-source/assignbot/-/blob/branch/default/assignbot/__main__.py#L173
        return self.gl.http_put(
            f'/projects/{pj.id}/merge_requests/{mr_id}',
            query_data={'reviewer_ids': chosen[0].id, 'assignee_ids': chosen[1].id},
        )
