from tenacity import retry, stop_after_attempt, wait_fixed

from lain_cli.utils import RegistryUtils, RequestClientMixin, tell_cluster_config


class Registry(RequestClientMixin, RegistryUtils):
    headers = {'Accept': 'application/vnd.docker.distribution.manifest.v2+json'}

    def __init__(self, host=None):
        if not host:
            cc = tell_cluster_config()
            host = cc['registry']

        self.host = host
        self.endpoint = f'http://{host}'

    def list_repos(self):
        path = '/v2/_catalog'
        responson = self.get(path, params={'n': 9999}, timeout=90).json()
        return responson.get('repositories', [])

    @retry(reraise=True, wait=wait_fixed(2), stop=stop_after_attempt(6))
    def delete_image(self, repo, tag=None):
        path = '/v2/{}/manifests/{}'.format(repo, tag)
        headers = self.head(path).headers
        docker_content_digest = headers.get('Docker-Content-Digest')
        if not docker_content_digest:
            return
        path = f'/v2/{repo}/manifests/{docker_content_digest}'
        return self.delete(path, timeout=20)  # 不知道为啥删除操作就是很慢, 只好在这里单独放宽

    def list_tags(self, repo_name, n=None, timeout=90):
        path = f'/v2/{repo_name}/tags/list'
        responson = self.get(path, params={'n': 99999}, timeout=timeout).json()
        if 'tags' not in responson:
            return []
        tags = self.sort_and_filter(responson.get('tags') or [], n=n)
        return tags
