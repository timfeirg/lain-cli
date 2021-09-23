import gitlab

from lain_cli.utils import error, must_get_env, tell_cluster_config


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

    def is_approved(self, project, mr_id):
        pj = self.gl.projects.get(project)
        mr = pj.mergerequests.get(mr_id)
        approvals = mr.approvals.get()
        return approvals.approved
