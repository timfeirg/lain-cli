from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)
from tencentcloud.cvm.v20170312 import cvm_client
from tencentcloud.cvm.v20170312 import models as cvm_models
from tencentcloud.tcr.v20190924 import models as tcr_models
from tencentcloud.tcr.v20190924.tcr_client import TcrClient

from lain_cli.utils import (
    RegistryUtils,
    debug,
    error,
    jalo,
    tell_cluster_config,
    warn,
)


class TencentClient(RegistryUtils):

    """https://cloud.tencent.com/document/product/1141/41605"""

    VM_STATES = {'on', 'off'}

    def __init__(
        self, registry=None, access_key_id=None, access_key_secret=None, **kwargs
    ):
        if not all([registry, access_key_id, access_key_secret]):
            cc = tell_cluster_config()
            registry = cc['registry']
            access_key_id = cc.get('access_key_id')
            access_key_secret = cc.get('access_key_secret')

        self.registry = registry
        self.repo_namespace = registry.split('/')[-1]
        if not all([access_key_id, access_key_secret]):
            raise ValueError(
                'access_key_id, access_key_secret not provided in cluster config'
            )

        self.cred = credential.Credential(access_key_id, access_key_secret)
        self.cvm_client = cvm_client.CvmClient(self.cred, "ap-beijing")
        self.tcr_client = TcrClient(self.cred, "ap-beijing")

    def list_repos(self):
        req = tcr_models.DescribeImagePersonalRequest()
        req.Limit = 100
        try:
            responson = jalo(
                self.tcr_client.DescribeRepositoryOwnerPersonal(req).to_json_string()
            )
        except TencentCloudSDKException as e:
            if e.code == 'AuthFailure.SignatureExpire':
                raise
            return None
        repo_info = responson['Data']['RepoInfo']
        repos = [dic['RepoName'] for dic in repo_info]
        return repos

    def list_tags(self, repo_name, **kwargs):
        req = tcr_models.DescribeImagePersonalRequest()
        req.RepoName = f'{self.repo_namespace}/{repo_name}'
        req.Limit = 100
        try:
            responson = jalo(
                self.tcr_client.DescribeImagePersonal(req).to_json_string()
            )
        except TencentCloudSDKException as e:
            if e.code == 'AuthFailure.SignatureExpire':
                raise
            return None
        tags = self.sort_and_filter(
            (dic['TagName'] for dic in responson['Data']['TagInfo']), n=kwargs.get('n')
        )
        return tags

    @retry(
        reraise=True,
        wait=wait_fixed(2),
        stop=stop_after_attempt(60),
        retry=retry_if_exception_type(TencentCloudSDKException),
    )
    def turn_(self, InstanceIds=None, cluster=None, state: str = 'on'):
        if not InstanceIds:
            InstanceIds = tell_cluster_config(cluster).get('instance_ids')

        if not InstanceIds:
            warn('instance_ids not defined in cluster info, cannot proceed', exit=1)

        for id_ in InstanceIds:
            ids = [id_]
            if state.lower() == 'off':
                req = cvm_models.StopInstancesRequest()
                req.InstanceIds = ids
                req.ForceStop = True
                req.StoppedMode = 'STOP_CHARGING'
                try:
                    self.cvm_client.StopInstances(req)
                except TencentCloudSDKException as e:
                    if e.code == 'UnauthorizedOperation':
                        error(f'weird error: {e.code}', exit=True)
                    if e.code != 'InvalidInstanceState.Stopped':
                        debug(f'retry due to {e.code}')
                        raise
            elif state.lower() == 'on':
                req = cvm_models.StartInstancesRequest()
                req.InstanceIds = ids
                try:
                    self.cvm_client.StartInstances(req)
                except TencentCloudSDKException as e:
                    if e.code not in {
                        'InvalidInstanceState.Running',
                        'UnsupportedOperation.InstanceStateRunning',
                    }:
                        debug(f'retry due to {e.code}')
                        raise
            else:
                error(f'weird state {state}, choose from {self.VM_STATES}', exit=True)


TencentRegistry = TencentClient
