from lain_cli.utils import (
    RegistryUtils,
    RequestClientMixin,
    flatten_list,
    tell_cluster_config,
)


class HarborRegistry(RequestClientMixin, RegistryUtils):
    def __init__(self, registry=None, harbor_token=None, **kwargs):
        if not all([registry, harbor_token]):
            cc = tell_cluster_config()
            registry = cc['registry']
            if 'harbor_token' not in cc:
                raise ValueError('harbor_token not provided in cluster config')
            harbor_token = cc['harbor_token']

        self.registry = registry
        try:
            host, project = registry.split('/')
        except ValueError as e:
            raise ValueError(f'bad registry: {registry}') from e
        self.endpoint = f'http://{host}/api/v2.0'
        self.headers = {
            # get from your harbor console
            'authorization': f'Basic {harbor_token}',
            'accept': 'application/json',
        }
        self.project = project

    def request(self, *args, **kwargs):
        res = super().request(*args, **kwargs)
        responson = res.json()
        if not isinstance(responson, dict):
            return res
        errors = responson.get('errors')
        if errors:
            raise ValueError(f'harbor error: {errors}')
        return res

    def list_repos(self):
        res = self.get(
            f'/projects/{self.project}/repositories', params={'page_size': 100}
        )
        responson = res.json()
        repos = [dic['name'].split('/')[-1] for dic in responson]
        return repos

    def list_tags(self, repo_name, **kwargs):
        repo_name = repo_name.split('/')[-1]
        res = self.get(
            f'/projects/{self.project}/repositories/{repo_name}/artifacts',
            params={'page_size': 100},
        )
        responson = res.json()
        tag_dics = flatten_list([dic['tags'] for dic in responson if dic['tags']])
        tags = self.sort_and_filter(
            (tag['name'] for tag in tag_dics), n=kwargs.get('n')
        )
        return tags
