from inspect import cleandoc
from urllib.parse import urlparse

from tenacity import retry, stop_after_attempt, wait_fixed

from lain_cli.utils import (
    RequestClientMixin,
    context,
    diff_dict,
    ensure_str,
    git,
    rc,
    tell_cherry,
    tell_executor,
    template_env,
)


def tell_webhook_client(hook_url=None):
    ctx = context()
    obj = ctx.obj
    config = obj.get('values', {}).get('webhook', {})
    hook_url = hook_url or config.get('url')
    if not hook_url:
        return
    clusters_to_notify = config.pop('clusters', None) or set()
    cluster = obj['cluster']
    if clusters_to_notify and cluster not in clusters_to_notify:
        return
    pr = urlparse(hook_url)
    if pr.netloc == 'open.feishu.cn':
        return FeishuWebhook(hook_url, **config)
    if pr.netloc == 'hooks.slack.com':
        return SlackIncomingWebhook(hook_url, **config)
    raise NotImplementedError(f'webhook not implemented for {hook_url}')


class Webhook(RequestClientMixin):

    endpoint = None
    deploy_message_template = template_env.get_template('deploy-webhook-message.txt.j2')
    k8s_secret_diff_template = template_env.get_template('k8s-secret-diff.txt.j2')

    def __init__(self, endpoint=None, **kwargs):
        self.endpoint = endpoint

    def send_msg(self, msg):
        raise NotImplementedError

    def diff_k8s_secret(self, old, new):
        secret_name = old['metadata']['name']
        diff = diff_dict(old['data'], new['data'])
        if not sum(len(l) for l in diff.values()):
            # do not send notification on empty diff
            return
        ctx = context()
        report = self.k8s_secret_diff_template.render(
            secret_name=secret_name,
            executor=tell_executor(),
            cluster=ctx.obj['cluster'],
            **diff,
        )
        return self.send_msg(report)

    def send_deploy_message(
        self, stderr=None, rollback_revision=None, previous_revision=None
    ):
        ctx = context()
        obj = ctx.obj
        git_revision = obj.get('git_revision')
        if git_revision:
            res = git(
                'log',
                '-n',
                '1',
                '--pretty=format:%s',
                git_revision,
                check=False,
                capture_output=True,
            )
            if rc(res):
                commit_msg = ensure_str(res.stderr)
            else:
                commit_msg = ensure_str(res.stdout)
        else:
            commit_msg = 'N/A'

        if previous_revision:
            cherry = tell_cherry(git_revision=previous_revision, capture_output=True)
        else:
            cherry = ''

        executor = tell_executor()
        text = self.deploy_message_template.render(
            executor=executor,
            commit_msg=commit_msg,
            stderr=stderr,
            cherry=cherry,
            rollback_revision=rollback_revision,
            **ctx.obj,
        )
        return self.send_msg(text)


class FeishuWebhook(Webhook):
    @retry(reraise=True, wait=wait_fixed(2), stop=stop_after_attempt(6))
    def send_msg(self, msg):
        payload = {
            'msg_type': 'text',
            'content': {
                'text': cleandoc(msg),
            },
        }
        return self.post(json=payload)


class SlackIncomingWebhook(Webhook):
    def __init__(self, endpoint=None, **kwargs):
        super().__init__(endpoint=endpoint, **kwargs)
        channel = kwargs.get('channel')
        if not channel:
            raise ValueError(
                'must define webhook.channel when using SlackIncomingWebhook'
            )
        self.channel = channel

    @retry(reraise=True, wait=wait_fixed(2), stop=stop_after_attempt(6))
    def send_msg(self, msg):
        payload = {
            'channel': self.channel,
            'text': msg,
        }
        return self.post(json=payload)
