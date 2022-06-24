import re

from aliyunsdkcore.acs_exception.exceptions import ServerException
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest
from aliyunsdkcr.request.v20160607 import GetRepoTagsRequest

from lain_cli.utils import (
    PaaSUtils,
    echo,
    error,
    jalo,
    tell_cluster_config,
    goodjob,
    warn,
)


class AliyunPaaS(PaaSUtils):

    TYPE = 'aliyun'

    def __init__(
        self,
        access_key_id=None,
        access_key_secret=None,
        registry=None,
        region_id=None,
        **kwargs,
    ):
        if not all([access_key_id, access_key_secret, registry]):
            cc = tell_cluster_config()
            access_key_id = cc.get('access_key_id')
            access_key_secret = cc.get('access_key_secret')
            if not registry and cc.get('registry_type') == self.TYPE:
                registry = cc['registry']

            if not all([access_key_id, access_key_secret]):
                raise ValueError(
                    'access_key_id / access_key_secret not provided in cluster config'
                )

        if registry:
            _, region_id, _, _, repo_namespace = re.split(r'[\./]', registry)
            self.registry = f'registry.{region_id}.aliyuncs.com/{repo_namespace}'
            self.repo_namespace = repo_namespace
        else:
            region_id = 'cn-hangzhou'

        self.acs_client = AcsClient(access_key_id, access_key_secret, region_id)
        self.endpoint = f'cr.{region_id}.aliyuncs.com'

    def list_tags(self, repo_name, **kwargs):
        request = GetRepoTagsRequest.GetRepoTagsRequest()
        request.set_RepoNamespace(self.repo_namespace)
        request.set_RepoName(repo_name)
        request.set_endpoint(self.endpoint)
        request.set_PageSize(100)
        try:
            response = self.acs_client.do_action_with_exception(request)
        except ServerException as e:
            if e.http_status == 404:
                return None
            if e.http_status == 400:
                warn(f'error during aliyun api query: {e}')
                return None
            raise
        tags_data = jalo(response)['data']['tags']
        tags = self.sort_and_filter((d['tag'] for d in tags_data), n=kwargs.get('n'))
        return tags

    def upload_tls_certificate(self, crt, key):
        """https://help.aliyun.com/document_detail/126557.htm"""
        name = self.tell_certificate_upload_name(crt)
        request = CommonRequest()
        request.set_accept_format('json')
        request.set_domain('cas.aliyuncs.com')
        request.set_method('POST')
        request.set_protocol_type('https')
        request.set_version('2018-07-13')
        request.set_action_name('CreateUserCertificate')
        request.add_query_param('Name', name)
        request.add_query_param('Cert', crt)
        request.add_query_param('Key', key)
        response = self.acs_client.do_action(request)
        res = jalo(response)
        code = res.get('Code')
        if code:
            if 'name already exists' in res.get('Message'):
                echo(f'certificate already uploaded: {res}')
            else:
                error(f'error during upload: {res}', exit=1)
        else:
            goodjob(f'certificate uploaded: {res}')
