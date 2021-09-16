from lain_cli.utils import (
    RegistryUtils,
    RequestClientMixin,
    flatten_list,
    tell_cluster_config,
)


class HarborRegistry(RequestClientMixin, RegistryUtils):
    def __init__(self, registry_url=None, token=None):
        if not all([registry_url, token]):
            cc = tell_cluster_config()
            registry_url = cc['registry']
            if 'harbor_token' not in cc:
                raise ValueError('harbor_token not provided in cluster config')
            token = cc['harbor_token']

        self.host = registry_url
        host, project = registry_url.split('/')
        self.endpoint = f'http://{host}/api/v2.0'
        self.headers = {
            # get from your harbor console
            'authorization': f'Basic {token}',
            'accept': 'application/json',
        }
        self.project = project

    def list_repos(self):
        res = self.get(f'/projects/{self.project}/repositories')
        responson = res.json()
        return responson

    def list_tags(self, appname, **kwargs):
        res = self.get(
            f'/projects/{self.project}/repositories/{appname}/artifacts',
            params={'page_size': 50},
        )
        responson = res.json()
        tag_dics = flatten_list([dic['tags'] for dic in responson if dic['tags']])
        tags = self.sort_and_filter(
            (tag['name'] for tag in tag_dics), n=kwargs.get('n')
        )
        return tags
