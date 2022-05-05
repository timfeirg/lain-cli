import asyncio
import base64
import inspect
import itertools
import json
import math
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping
from contextlib import contextmanager, suppress
from copy import deepcopy
from functools import lru_cache, partial
from glob import glob
from hashlib import blake2b
from inspect import cleandoc
from io import BytesIO
from numbers import Number
from os import fdopen
from os import getcwd as cwd
from os import getppid, makedirs, readlink, remove, unlink
from os.path import abspath, basename, dirname, exists, expanduser, isdir, isfile, join
from tempfile import TemporaryDirectory, mkstemp
from time import sleep, time

import click
import psutil
import requests
from click import BadParameter
from humanfriendly import (
    CombinedUnit,
    SizeUnit,
    parse_size,
    parse_timespan,
    round_number,
)
from humanfriendly.text import tokenize
from jinja2 import Environment, FileSystemLoader
from marshmallow import INCLUDE, Schema, ValidationError, post_load, validates
from marshmallow.fields import Dict, Field, Function, Int, List, Nested, Raw, Str
from marshmallow.schema import SchemaMeta
from marshmallow.validate import NoneOf, OneOf
from packaging import version
from pip._internal.index.collector import LinkCollector
from pip._internal.index.package_finder import PackageFinder
from pip._internal.models.search_scope import SearchScope
from pip._internal.models.selection_prefs import SelectionPreferences
from pip._internal.network.session import PipSession
from requests.exceptions import RequestException
from ruamel.yaml import YAML
from ruamel.yaml.parser import ParserError
from ruamel.yaml.scalarstring import LiteralScalarString

from lain_cli import __version__

yaml = YAML()
ENV = os.environ.copy()
# safe to delete when release is in this state
HELM_STUCK_STATE = {'pending-install', 'pending-upgrade', 'uninstalling'}
CLI_DIR = dirname(abspath(__file__))
TEMPLATE_DIR = join(CLI_DIR, 'templates')
CHART_TEMPLATE_DIR = join(CLI_DIR, 'chart_template')
CLUSTER_VALUES_DIR = ENV.get('LAIN_CLUSTER_VALUES_DIR') or join(
    CLI_DIR, 'cluster_values'
)
template_env = Environment(
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
    loader=FileSystemLoader([CHART_TEMPLATE_DIR, TEMPLATE_DIR]),
    extensions=['jinja2.ext.loopcontrols'],
)
CHART_DIR_NAME = 'chart'
CHART_VERSION = version.parse('0.1.11')
LOOKOUT_ENV = {'http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'}
KUBECONFIG_DIR = expanduser('~/.kube')
HELM_MIN_VERSION_STR = 'v3.8.0'
HELM_MIN_VERSION = version.parse(HELM_MIN_VERSION_STR)
STERN_MIN_VERSION_STR = '1.11.0'
STERN_MIN_VERSION = version.parse(STERN_MIN_VERSION_STR)
TIMESTAMP_PATTERN = re.compile(r'\d+')
LAIN_META_PATTERN = re.compile(r'\d{10,}-\w{40}$')
KUBERNETES_MIN_MEMORY = parse_size('4MiB', binary=True)
# lain build config
DEFAULT_WORKDIR = '/lain/app'
DOCKER_COMPOSE_FILE_PATH = 'docker-compose.yaml'
DOCKERFILE_NAME = 'Dockerfile'
DOCKERIGNORE_NAME = '.dockerignore'
GITIGNORE_NAME = '.gitignore'
BUILD_STAGES = {'prepare', 'build', 'release'}
PROTECTED_REPO_KEYWORDS = ('centos',)
RECENT_TAGS_COUNT = 10
BIG_DEPLOY_REPLICA_COUNT = 3
INGRESS_CANARY_ANNOTATIONS = {
    'nginx.ingress.kubernetes.io/canary-by-header',
    'nginx.ingress.kubernetes.io/canary-by-header-value',
    'nginx.ingress.kubernetes.io/canary-by-header-pattern',
    'nginx.ingress.kubernetes.io/canary-by-cookie',
    'nginx.ingress.kubernetes.io/canary-weight',
}
DEFAULT_BACKEND_RESPONSE = 'default backend - 404'


def parse_multi_timespan(s):
    """
    >>> parse_multi_timespan('3s')
    3.0
    >>> parse_multi_timespan('3h3s')
    10800.0
    """
    tokens = tokenize(s)
    s = ''.join((str(c) for c in tokens[:2]))
    return parse_timespan(s)


def click_parse_timespan(ctx, param, value):
    if not value:
        return
    if isinstance(value, Number):
        return int(value)
    return int(parse_timespan(value))


class DuplicationInValues(Exception):
    """lain hates duplication in values"""


def recursive_update(d, u, ignore_extra=False, prevent_duplication=False):
    """
    >>> recursive_update({'foo': {'spam': 'egg'}, 'should': 'preserve'}, {'foo': {'bar': 'egg'}})
    {'foo': {'spam': 'egg', 'bar': 'egg'}, 'should': 'preserve'}
    >>> recursive_update({'foo': 'xxx'}, {'foo': {'bar': 'egg'}})
    {'foo': {'bar': 'egg'}}
    >>> recursive_update({'foo': 'xxx'}, {'bar': {'not': 'included'}}, ignore_extra=True)
    {'foo': 'xxx'}
    """
    if not u:
        return d
    for k, v in u.items():
        if ignore_extra and k not in d:
            continue
        if type(d.get(k)) is not type(v):
            d[k] = v
        elif isinstance(v, Mapping):
            d[k] = recursive_update(d.get(k, {}), v)
        else:
            if prevent_duplication:
                old = d.get(k)
                if old == v:
                    raise DuplicationInValues(f'duplication key: {k}, values: {old}')
            d[k] = v
    return d


def quote(s):
    return shlex.quote(s)


def diff_dict(old, new):
    """
    >>> diff_dict({'del': '0', 'change': '0', 'stay': '0'}, {'change': '1', 'stay': '0', 'add': '0'})
    {'added': ['add'], 'removed': ['del'], 'changed': ['change']}
    """
    all_keys = set(old) | set(new)
    diff = {'added': [], 'removed': [], 'changed': []}
    for k in all_keys:
        lv = old.get(k)
        rv = new.get(k)
        if not lv:
            diff['added'].append(k)
        elif not rv:
            diff['removed'].append(k)
        elif lv != rv:
            diff['changed'].append(k)

    return diff


def context(silent=False):
    return click.get_current_context(silent=silent)


def excall(s, silent=None):
    """lain cli often calls other cli, might wanna notify the user what's being
    run"""
    # when running tests, this function will be invoked without a active click
    # context personally i hate adding extra handling in business code just to
    # take care of testing, forgive me because there's gonna be much more work
    # otherwise
    ctx = context(silent=True)
    if silent or ctx and ctx.obj.get('silent'):
        return
    if not isinstance(s, str):
        s = subprocess.list2cmdline(s)

    click.echo(click.style(s, fg='bright_yellow'), err=True)


def ensure_str(s):
    try:
        return s.decode('utf-8')
    except Exception:
        return str(s)


def echo(s, fg=None, exit=None, err=False, clean=True):
    if s is None:
        return
    s = ensure_str(s)
    if clean:
        s = cleandoc(s)

    click.echo(click.style(s, fg=fg), err=err)
    ctx = context(silent=True)
    if ctx:
        if isinstance(exit, bool):
            if exit:
                ctx.exit(0)
        elif isinstance(exit, int):
            ctx.exit(exit)


def goodjob(s, exit=None, **kwargs):
    if exit:
        exit = 0

    return echo(s, fg='green', exit=exit, err=True, **kwargs)


def warn(s, exit=None, **kwargs):
    if exit:
        exit = 1

    return echo(s, fg='magenta', exit=exit, err=True, **kwargs)


def debug(s, exit=None, **kwargs):
    ctx = context(silent=True)
    if ctx and not ctx.obj.get('verbose'):
        return
    if exit:
        exit = 1

    return echo(s, fg='black', exit=exit, err=True, **kwargs)


def error(s, exit=None, **kwargs):
    if exit:
        exit = 1

    return echo(s, fg='red', exit=exit, err=True, **kwargs)


def flatten_list(nested_list):
    return list(itertools.chain.from_iterable(nested_list))


def must_get_env(name, fail_msg=''):
    val = ENV.get(name)
    if not val:
        error(f'environment variable {name} not defined: {fail_msg}', exit=True)

    return val


def tell_pods_count():
    ctx = context()
    values = ctx.obj['values']
    count = sum(proc.get('replicaCount', 1) for proc in values['deployments'].values())
    return count


def tell_pod_deploy_name(s):
    """
    >>> tell_pod_deploy_name('dummy-web-dev-7557696ddf-52cc6')
    'dummy-web-dev'
    >>> tell_pod_deploy_name('dummy-web-7557696ddf-52cc6')
    'dummy-web'
    """
    return s.rsplit('-', 2)[0]


def tell_domain_suffix(cc):
    domain_suffix = cc.get('domain_suffix')
    if not domain_suffix:
        domain = cc.get('domain')
        domain_suffix = f'.{domain}' if domain else ''

    return domain_suffix


def make_external_url(host, paths=None, port=80):
    host_port = f'{host}'
    if port != 80:
        host_port += f':{port}'

    paths = paths or ['/']
    for path in paths:
        yield f'http://{host_port}{path}'
        yield f'https://{host_port}{path}'


def make_internal_url(host, paths=None, port=80, domain_suffix=None):
    """internal ingress host can be either full domain or just the first
    part (usually appname)"""
    host_port = f'{host}' if '.' in host else f'{host}{domain_suffix}'
    if port != 80:
        host_port += f':{port}'

    paths = paths or ['/']
    for path in paths:
        yield f'http://{host_port}{path}'
        yield f'https://{host_port}{path}'


def tell_ingress_urls():
    ctx = context()
    values = ctx.obj['values']
    ingresses = values.get('ingresses') or []
    cc = tell_cluster_config()
    if not cc:
        return
    domain_suffix = tell_domain_suffix(cc)
    ingress_internal_port = cc.get('ingress_internal_port', 80)
    ingress_external_port = cc.get('ingress_external_port', 80)
    part1 = itertools.chain.from_iterable(
        [
            make_internal_url(
                i['host'],
                paths=i['paths'],
                port=ingress_internal_port,
                domain_suffix=domain_suffix,
            )
            for i in ingresses
        ]
    )
    externalIngresses = values.get('externalIngresses') or []
    part2 = itertools.chain.from_iterable(
        make_external_url(i['host'], paths=i['paths'], port=ingress_external_port)
        for i in externalIngresses
    )
    return list(part1) + list(part2)


def parse_ready(ready_str):
    """
    >>> parse_ready('0/1')
    False
    >>> parse_ready('1/1')
    True
    """
    left, right = ready_str.split('/')
    if left != right:
        return False
    return True


def parse_podline(s):
    """
    >>> new = 'dummy-web-8d9c66df6-8wffw   0/1     RunContainerError   1 (18s ago)   39s   172.17.0.4   minikube   <none>           <none>'
    >>> parse_podline(new)
    ['dummy-web-8d9c66df6-8wffw', '0/1', 'RunContainerError', '1', '39s', '172.17.0.4', 'minikube', '<none>', '<none>']
    >>> old = 'dummy-web-8d9c66df6-8wffw   0/1     RunContainerError   1   39s   172.17.0.4   minikube   <none>           <none>'
    >>> parse_podline(old)
    ['dummy-web-8d9c66df6-8wffw', '0/1', 'RunContainerError', '1', '39s', '172.17.0.4', 'minikube', '<none>', '<none>']
    """
    parentheses_removed = re.sub(r'\([^()]*\)', '', s)
    return parentheses_removed.split()


def get_pods(
    appname=None, selector=None, headers=False, show_only_bad_pods=None, check=False
):
    cmd = [
        'get',
        'pod',
        '-o=wide',
    ]
    if appname and selector:
        raise ValueError(
            f'cannot use appname and selector together, got {appname}, {selector}'
        )
    if appname:
        selector = f'app.kubernetes.io/name={appname}'

    if selector:
        cmd.append(f'-l{selector}')

    res = kubectl(*cmd, capture_output=True, check=check)
    pods = ensure_str(res.stdout).splitlines()
    if not show_only_bad_pods:
        if headers:
            return res, pods
        return res, pods[1:]
    header = pods.pop(0)
    bad_pods = []
    for podline in pods:
        # ['deploy-x-x', '1/1', 'Running', '0', '6h6m', '192.168.0.13', 'node-1', '<none>', '1/1']
        _, ready_str, status, restarts, *_ = podline.split()
        if status == 'Completed':
            # job pods will be ignored
            continue
        if not parse_ready(ready_str):
            bad_pods.append(podline)
            continue
        if status not in {'Running', 'Completed'}:
            # 状态异常的 pods 是我们最为关心的, 因此塞到头部方便取用
            bad_pods.insert(1, podline)
            continue
        if int(restarts) > 10:
            # 本来时不时就会重启节点, 造成容器重启, 因此设置个小阈值, 过滤噪声
            bad_pods.append(podline)
            continue

    if headers:
        return res, [header] + bad_pods
    return res, bad_pods


def pick_pod(proc_name=None, phase=None, containerStatuses=None, selector=None):
    release_name = tell_release_name()
    cmd = ['get', 'pod', '-o=json']
    if proc_name:
        cmd.extend(['-l', f'app.kubernetes.io/instance={release_name}-{proc_name}'])
    elif selector:
        cmd.extend(['-l', selector])
    else:
        cmd.extend(['-l', f'helm.sh/chart={release_name}'])

    if phase:
        cmd.extend([f'--field-selector=status.phase=={phase}'])

    res = kubectl(*cmd, capture_output=True, check=False)
    stdout = res.stdout
    if not stdout or rc(res):
        return
    responson = jalo(res.stdout)
    if containerStatuses:
        if not isinstance(containerStatuses, set):
            containerStatuses = {containerStatuses}

        # 这个数据的 parsing 真不用看, 随便 k get po -ojson
        # 看眼结构就知道怎么做 parsing 了, 不用怪我不封装
        items = [
            item
            for item in responson['items']
            if containerStatuses.intersection(
                set(
                    (
                        status['state'].get('waiting', {})
                        or status['state'].get('terminated', {})
                    ).get('reason')
                    for status in item['status'].get('containerStatuses', [])
                )
            )
        ]
    else:
        items = responson['items']

    items = sorted(items, key=lambda d: d['metadata']['creationTimestamp'])
    podnames = [item['metadata']['name'] for item in items]
    try:
        return podnames[-1]
    except IndexError:
        return


def tell_best_deploy():
    """deployment name with the most memory"""
    ctx = context()
    deploys = ctx.obj['values']['deployments']
    chosen = list(deploys.keys())[0]

    def mem_limits(deploy):
        mem_str = deploy.get('resources', {}).get('limits', {}).get('memory') or '1Gi'
        return parse_size(mem_str)

    for name, deploy in deploys.items():
        left = deploys[chosen]
        if mem_limits(deploy) > mem_limits(left):
            chosen = name

    return chosen


def delete_pod(selector, graceful=False):
    _, pods = get_pods(selector=selector, check=True)
    if not pods:
        error(f'no pods found with {selector}', exit=1)

    if not graceful:
        return kubectl('delete', 'pod', '-l', selector, timeout=None)
    for line in pods:
        pod_name = line.split(None, 1)[0]
        res = kubectl(
            'delete',
            'pod',
            '--wait=true',
            pod_name,
            timeout=None,
            tee=True,
            check=False,
        )
        if code := rc(res):
            stderr = ensure_str(res.stderr)
            if 'NotFound' in stderr:
                warn(f'{pod_name} is already gone, ignore')
            else:
                error(f'cannot continue due to error: {stderr}', exit=code)

        wait_for_pod_up(selector=selector)


def deploy_toast(canary=False, re_creation_headsup=False):
    ctx = context()
    ctx.obj.update(tell_cluster_config())
    if canary:
        template = template_env.get_template('canary-toast.txt.j2')
    elif re_creation_headsup:
        warn(
            'container is not re-created, if you want to force re-creation, use lain restart [--graceful]'
        )
        url = lain_docs('errors.html#id4')
        warn(f'📖 learn more at {url}')
        return
    else:
        ctx.obj['kibana_url'] = tell_kibana_url()
        template = template_env.get_template('deploy-toast.txt.j2')

    goodjob(template.render(**ctx.obj))


def tell_grafana_url():
    release_name = tell_release_name()
    cc = tell_cluster_config()
    grafana_url = cc.get('grafana_url')
    if grafana_url:
        return f'{grafana_url}?orgId=1&refresh=10s&var-label_app={release_name}'


def open_kibana_url(release_name=None, proc=None):
    url = tell_kibana_url(release_name=release_name, proc=proc)
    subprocess_run(['open', url])


def tell_kibana_url(release_name=None, proc=None):
    if not release_name:
        release_name = tell_release_name()

    cc = tell_cluster_config()
    kibana_host = cc.get('kibana')
    if not kibana_host:
        return
    q = f'{release_name}-{proc}' if proc else release_name
    url = f'http://{kibana_host}/app/logs/stream?logPosition=(end:now,start:now-30m,streamLive:!f)&logFilter=(expression:%27kubernetes.pod_name.keyword:{q}*%27,kind:kuery)'
    return url


too_much_logs_headsup_str = '''lain logs didn't work, here's some tips:
    * use stern instead of kubectl logs, lain logs --stern
{%- if kibana %}
    * use kibana: {{ kibana_url }}
{%- endif %}
'''
too_much_logs_headsup_template = template_env.from_string(too_much_logs_headsup_str)


def too_much_logs_headsup():
    # kubectl cannot tail from more than 8 log streams, when that happens,
    # print a help message to redirect users to kibana, if applicable
    ctx = context()
    ctx.obj.update(tell_cluster_config())
    kibana_url = tell_kibana_url()
    headsup = too_much_logs_headsup_template.render(kibana_url=kibana_url, **ctx.obj)
    error(headsup)


init_done_str = f'''a helm chart is generated under the ./{CHART_DIR_NAME} directory. what's next?
* review and edit ./{CHART_DIR_NAME}/values.yaml
* add helm chart to git repo: git add ./{CHART_DIR_NAME}
* if this app needs secret files or env, you should create them:
    lain use [CLUSTER]
    lain [secret|env] edit
* lain deploy --build
'''


def init_done_toast():
    goodjob(init_done_str)


template_update_done_str = '''helm chart template has been updated, commit the changes and get on with your life.'''


def template_update_toast():
    goodjob(template_update_done_str)


class RequestClientMixin:
    endpoint = None
    headers = {}
    timeout = 5

    def request(self, method, path=None, params=None, data=None, **kwargs):
        if not path:
            url = self.endpoint
        elif self.endpoint:
            url = self.endpoint + path
        else:
            raise ValueError('no endpoint specified')

        kwargs.setdefault('timeout', self.timeout)
        res = requests.request(
            method, url, headers=self.headers, params=params, data=data, **kwargs
        )
        return res

    def post(self, path=None, **kwargs):
        return self.request('POST', path, **kwargs)

    def get(self, path=None, **kwargs):
        return self.request('GET', path, **kwargs)

    def delete(self, path=None, **kwargs):
        return self.request('DELETE', path, **kwargs)

    def head(self, path=None, **kwargs):
        return self.request('HEAD', path, **kwargs)


class RegistryUtils:
    registry = 'registry.fake/dev'

    @staticmethod
    def is_protected_repo(repo):
        for s in PROTECTED_REPO_KEYWORDS:
            if s in repo:
                return True
        return False

    @staticmethod
    def parse_image_ts(s):
        if s == 'latest':
            return sys.maxsize
        res = TIMESTAMP_PATTERN.search(s)
        ts = int(res.group()) if res else 0
        return ts

    @staticmethod
    def sort_and_filter(tags, n=None):
        n = n or RECENT_TAGS_COUNT
        cleaned = sorted((s for s in tags if not s.startswith('prepare')), reverse=True)
        if n:
            return cleaned[:n]
        return cleaned

    def make_image(self, tag, repo=None):
        ctx = context()
        if not repo:
            repo = ctx.obj['appname']

        return f'{self.registry}/{repo}:{tag}'

    def list_repos(self):
        raise NotImplementedError

    def list_tags(self, repo_name):
        raise NotImplementedError

    def list_images(self):
        repos = self.list_repos()
        images = []
        for repo in repos:
            tags = set(self.list_tags(repo))
            images.extend([self.make_image(tag, repo=repo) for tag in tags])

        return images


def tell_registry_client(cc=None):
    if not cc:
        cc = tell_cluster_config()

    registry_type = cc.get('registry_type') or 'registry'
    if registry_type == 'registry':
        from lain_cli.registry import Registry

        return Registry(**cc)
    if registry_type == 'aliyun':
        from lain_cli.aliyun import AliyunRegistry

        return AliyunRegistry(**cc)
    if registry_type == 'harbor':
        from lain_cli.harbor import HarborRegistry

        return HarborRegistry(**cc)
    if registry_type == 'tencent':
        from lain_cli.tencent import TencentRegistry

        return TencentRegistry(**cc)
    warn(f'unsupported registry type: {registry_type}')


def clean_kubernetes_manifests(yml):
    """remove irrelevant information from Kubernetes manifests"""
    yml.pop('status', '')
    metadata = yml.get('metadata', {})
    metadata.pop('creationTimestamp', '')
    metadata.pop('selfLink', '')
    metadata.pop('uid', '')
    metadata.pop('resourceVersion', '')
    metadata.pop('generation', '')
    metadata.pop('managedFields', '')
    annotations = metadata.get('annotations', {})
    annotations.pop('kubectl.kubernetes.io/last-applied-configuration', '')
    spec = yml.get('spec', {})
    spec.pop('clusterIP', None)


def dump_secret(secret_name, init='env'):
    """create a tempfile and dump plaintext secret into it"""
    secret_dic = tell_secret(secret_name, init=init)
    fd, name = mkstemp(suffix='.yaml')
    yadu(secret_dic, fd)
    return name


def tell_secret(secret_name, init='env'):
    """return Kubernetes secret object in python dict, all b64decoded.
    If secret doesn't exist, create one first, and with some example content"""

    res = kubectl(
        'get', 'secret', '-oyaml', secret_name, capture_output=True, check=False
    )
    if code := rc(res):
        stderr = ensure_str(res.stderr)
        if 'not found' in stderr:
            init_kubernetes_secret(secret_name, init=init)
            return tell_secret(secret_name, init=init)
        error(f'weird error: {stderr}', exit=code)

    dic = yalo(res.stdout)
    clean_kubernetes_manifests(dic)
    dic.setdefault('data', {})
    for fname, s in dic['data'].items():
        decoded = base64.b64decode(s).decode('utf-8') if s else ''
        # gotta do this so yaml.dump will print nicely
        dic['data'][fname] = (
            LiteralScalarString(decoded) if '\n' in decoded else decoded
        )

    return dic


def init_kubernetes_secret(secret_name, init='env'):
    d = TemporaryDirectory()
    if init == 'env':
        init_clause = '--from-literal=FOO=BAR'
    elif init == 'secret':
        example_file = 'topsecret.txt'
        example_file_path = join(d.name, example_file)
        with open(example_file_path, 'w') as f:
            f.write('I\nAM\nBATMAN')

        init_clause = f'--from-file={example_file_path}'
    else:
        raise ValueError(f'init style: env, secret. dont\'t know what this is: {init}')
    kubectl(
        'create',
        'secret',
        'generic',
        secret_name,
        init_clause,
        capture_output=True,
        check=True,
    )
    d.cleanup()  # don't wanna cleanup too early


def kubectl_edit(f, capture_output=False, notify_diff=True, **kwargs):
    webhook = None
    if notify_diff:
        from lain_cli.webhook import tell_webhook_client

        webhook = tell_webhook_client()
        if webhook:
            old = yalo(f)

    current_cluster = tell_cluster()
    edit_file(f)
    try:
        secret_dic = yalo(f)
        if notify_diff:
            new = deepcopy(secret_dic)

        cluster = tell_cluster()
        ctx = context()
        if cluster != current_cluster:
            will_exit = not ctx.obj.get('ignore_lint')
            error(
                f'during editing, you have switched from {current_cluster} to {cluster}',
                exit=will_exit,
            )

        res = kubectl_apply(secret_dic, capture_output=capture_output, **kwargs)
    except (ParserError, ValueError, KeyError) as e:
        err = f'''not a valid kubernetes secret file after edit:
            {repr(e)}

            don't worry, your work has been saved to: {f}'''
        error(err, exit=1)

    if rc(res):
        err = f'''
        error during kubectl apply (read the above error).
        don't worry, your work has been saved to: {f}'''
        error(err, exit=1)

    if notify_diff and webhook:
        webhook.diff_k8s_secret(old, new)

    return res


def kubectl_apply(
    anything,
    validate=True,
    capture_output=False,
    check=True,
    backup=False,
    **kwargs,
):
    """dump content into a temp yaml file, and then k apply.
    also if this thing is kubernetes secret, will try to b64encode"""
    if isinstance(anything, str):
        dic = yalo(anything)
    elif isinstance(anything, dict):
        dic = anything
    else:
        raise ValueError(
            f'argument must be dict or yaml / json string, got: {anything}'
        )
    if dic['kind'] == 'Secret':
        data = dic.get('data') or {}
        for k, s in data.items():
            try:
                dic['data'][k] = base64.b64encode(s.encode('utf-8')).decode('utf-8')
            except AttributeError as e:
                raise ValueError(
                    f'kubernetes secret data should be string, got {k}: {s}'
                ) from e

    debug('dumping kubernetes manifest:')
    debug(dic)
    fd, name = mkstemp(suffix='.yaml')
    yadu(dic, fd)
    validate = jadu(validate)
    try:
        res = kubectl(
            'apply',
            '-f',
            name,
            f'--validate={validate}',
            capture_output=capture_output,
            check=check,
            **kwargs,
        )
        ctx = context(silent=True)
        auto_pilot = ctx and ctx.obj.get('auto_pilot')
        changed = tell_change_from_kubectl_output(ensure_str(res.stdout))
        if not auto_pilot and changed:
            goodjob(
                'secret changes will not take effect until pod is re-created, one way to do this is lain restart --graceful'
            )

        if changed and backup:
            backup_kubernetes_resource(dic)

        return res
    finally:
        unlink(name)


def backup_kubernetes_resource(dic):
    resource_name = dic['metadata']['name']
    ts = int(time())
    dic['metadata']['name'] = f'{resource_name}-backup-{ts}'
    backup_fd, backup_name = mkstemp(suffix='.yaml')
    yadu(dic, backup_fd)
    try:
        kubectl(
            'apply',
            '-f',
            backup_name,
            '--validate=false',
            capture_output=False,
        )
    finally:
        unlink(backup_name)


def tell_change_from_kubectl_output(stdout):
    if 'configured' in stdout:
        return True
    return False


def tell_executor():
    exe = ENV.get('USER')
    if not exe:
        # gitlab ci job url, and the user who started this job
        gitlab_user_name = ENV.get('GITLAB_USER_NAME') or ''
        ci_job_url = ENV.get('CI_JOB_URL') or ''
        if gitlab_user_name:
            exe = f'{gitlab_user_name}-via-{ci_job_url}'
        else:
            exe = ci_job_url

    return exe


def tell_job_timeout():
    values = context().obj['values']
    jobs = values.get('jobs') or {}
    timeouts = set(job.get('activeDeadlineSeconds', 3600) for job in jobs.values())
    # if no job is defined, set helm timeout to 5m
    timeouts.add(300)
    return max(timeouts)


def check_correct_override(appname, partial_values):
    """if cluster-specific build is used, you should also override appname"""
    if not partial_values:
        return True
    if 'build' in partial_values:
        if appname == partial_values.get('appname'):
            return True
        return False
    return True


def tell_helm_options(kvpairs=None, deduce_image=True, canary=False, extra=()):
    """Sure you can override helm values, but I might not approve it"""
    kvdic = dict(kvpairs or ())
    ctx = context()
    cluster = ctx.obj['cluster']
    kvdic['cluster'] = cluster
    kvdic['user'] = tell_executor()
    repo_url = git_remote()
    if repo_url:
        kvdic['repo_url'] = repo_url

    image_tag = kvdic.get('imageTag')
    if deduce_image:
        image_tag = tell_image_tag(image_tag)

    if image_tag:
        kvdic['imageTag'] = ctx.obj['image_tag'] = image_tag
        if LAIN_META_PATTERN.match(image_tag):
            ctx.obj['git_revision'] = image_tag.split('-')[-1]

    set_clause = ','.join(f'{k}={v}' for k, v in kvdic.items())
    if isinstance(extra, str):
        extra = (extra,)
    else:
        extra = extra or ()

    options = ['--set', set_clause, *extra]

    internal_values_file = tell_cluster_values_file(internal=True)
    if internal_values_file:
        options.extend(['-f', internal_values_file])

    values_file = tell_cluster_values_file()
    if values_file:
        options.extend(['-f', values_file])

    extra_values_file = ctx.obj['extra_values_file']
    if extra_values_file:
        options.extend(['-f', extra_values_file.name])

    if canary:
        canary_values_file = create_canary_values()
        options.extend(['-f', canary_values_file])

    return options


def clean_canary_ingress_annotations(annotations):
    for k in INGRESS_CANARY_ANNOTATIONS:
        annotations.pop(k, None)


def make_canary_name(appname):
    return f'{appname}-canary'


def create_canary_values():
    template = template_env.get_template('values-canary.yaml.j2')
    canary_values_file = join(CHART_DIR_NAME, 'values-canary.yaml')
    ctx = context()
    with open(canary_values_file, 'w') as f:
        f.write(template.render(**ctx.obj))

    return canary_values_file


def delete_canary_values():
    canary_values_file = join(CHART_DIR_NAME, 'values-canary.yaml')
    ensure_absent(canary_values_file)


def tell_image_tag(image_tag=None):
    """really smart method to figure out which image_tag is the right one to deploy:
        1. if image_tag isn't provided, obtain from lain_meta
        2. check for existence against registry API
        3. if the provided image_tag doesn't exist, print helpful suggestions
        4. if no suggestions at all, give up and return None
    """
    ctx = context()
    values = ctx.obj['values']
    use_lain_build = 'build' in values
    if not use_lain_build:
        # 如果压根不用 lain build, 那么也无法通过查询 registry 来推断镜像 tag
        return image_tag
    if not image_tag:
        image_tag = lain_meta()

    # 如果该集群的 registry 不支持查询, 那就没什么好检查的了
    registry = tell_registry_client()
    if not registry or ctx.obj.get('ignore_lint'):
        return image_tag
    appname = ctx.obj['appname']
    existing_tags = registry.list_tags(appname) or []
    if image_tag not in existing_tags:
        # when using lain deploy --build without using --set imageTag=xxx, we
        # can build the requested image for the user
        if ctx.obj.get('build_jit') and build_jit_challenge(image_tag):
            lain_('build', '--push')
            return image_tag

        recent_tags = RegistryUtils.sort_and_filter(existing_tags)[:RECENT_TAGS_COUNT]
        if not recent_tags:
            warn(f'no recent tags found in existing_tags: {existing_tags}')
            return image_tag
        latest_tag = recent_tags[0]
        recent_tags_str = '\n            '.join(recent_tags)
        caller_name = inspect.stack()[1].function
        if caller_name == 'update_image':
            amender = 'lain update-image --deduce'
        else:
            amender = f'lain deploy --set imageTag={latest_tag}'

        image = make_image_str(image_tag=image_tag)
        err = f'''
        Image not found: {image}.
        Did you forget to lain push? Try fix with lain deploy --build

        If you'd like to deploy the latest existing image:
            {amender}
        Or choose from a recent version:
            {recent_tags_str}
        See more using lain version
        '''
        error(err, exit=1)

    return image_tag


def lain_(*args, exit=None, **kwargs):
    ctx = context()
    extra_values_file = ctx.obj.get('extra_values_file')
    if extra_values_file:
        args = ['--values', extra_values_file.name, *args]

    cmd = ['lain', *args]
    kwargs.setdefault('check', True)
    kwargs.setdefault('env', ENV)
    if ctx.obj.get('ignore_lint'):
        kwargs['env']['LAIN_IGNORE_LINT'] = 'true'

    if ctx.obj.get('remote_docker'):
        kwargs['env']['LAIN_REMOTE_DOCKER'] = 'true'

    completed = subprocess_run(cmd, **kwargs)
    if exit:
        context().exit(rc(completed))

    return completed


def lain_image(stage='release'):
    if stage == 'prepare':
        return make_image_str(image_tag='prepare')
    if stage in BUILD_STAGES:
        image_tag = lain_meta()
        return make_image_str(image_tag=image_tag)
    raise ValueError(f'weird stage {stage}, choose from {BUILD_STAGES}')


def lain_meta():
    git_cmd = ['log', '-1', '--pretty=format:%ct-%H']
    res = git(*git_cmd, capture_output=True, silent=True, check=False)
    returncode = rc(res)
    if returncode:
        stderr = ensure_str(res.stderr)
        if 'not a git' in stderr.lower():
            return 'latest'
        error(stderr, exit=returncode)
        error('cannot calculate image tag, using latest')

    stdout = ensure_str(res.stdout)
    image_tag = stdout.strip()
    ctx = context(silent=True)
    if ctx:
        ctx.obj['lain_meta'] = image_tag

    return image_tag


def ensure_resource_initiated(chart=False, secret=False):
    ctx = context()
    if chart:
        if not isdir(CHART_DIR_NAME):
            error(
                'helm chart not initialized yet, run `lain init --help` to learn how',
                exit=1,
            )

    if secret:
        # if volumeMounts are used in values.yaml but secret doesn't exists,
        # print error and then exit
        values = ctx.obj['values']
        subPaths = [
            m['subPath'] for m in values.get('volumeMounts') or [] if m.get('subPath')
        ]
        secret_name = ctx.obj['secret_name']
        # 如果 values 里边定制过了 volumes, 就绕过检查吧, 肯定是高级用户
        if subPaths and not values.get('volumes'):
            cluster = ctx.obj['cluster']
            res = kubectl(
                'get', 'secret', secret_name, capture_output=True, check=False
            )
            code = rc(res)
            if code:
                tutorial = '\n'.join(f'lain secret add {f}' for f in subPaths)
                err = f'''
                Secret {subPaths} not found, you should create them:
                    lain use {cluster}
                    {tutorial}
                And if you ever need to add more files, env or edit them, do this:
                    lain secret edit
                '''
                error(err, exit=code)
        else:
            # don't mind me, just using this function to initiate a dummy secret
            tell_secret(secret_name)

    return True


def subprocess_run(
    *args, silent=None, dry_run=False, tee=False, abort_on_fail=False, **kwargs
):
    """Same in functionality, but better than subprocess.run

    Args:
        silent (bool): do not log subprocess commands.
        check (bool): will capture stderr, and print them on fail.
        tee (bool): capture, and print stdout / stderr.
        abort_on_fail (bool): call ctx.exit on fail, but does not capture any standard output.
    """
    # 这一段代码行为上肯定是多余的, 但是 run 内部不允许 capture_output 和
    # stdout / stderr 俩参数混用, 因此在这里进行适配
    capture_output = kwargs.pop('capture_output', None) or tee
    if capture_output:
        kwargs['stdout'] = subprocess.PIPE
        kwargs['stderr'] = subprocess.PIPE

    capture_error = kwargs.pop('capture_error', None)
    if capture_error:
        kwargs['stderr'] = subprocess.PIPE

    check = kwargs.pop('check', None)
    if check:
        kwargs['stderr'] = subprocess.PIPE

    if not silent:
        ctx = context(silent=True)
        silent = ctx and ctx.obj.get('silent')

    if kwargs.get('shell'):
        if not isinstance(args[0], str):
            args = list(args)
            args[0] = ' '.join(args[0])

    excall(*args, silent=silent)
    if dry_run:
        return
    try:
        res = subprocess.run(*args, **kwargs)
    except subprocess.TimeoutExpired:
        timeout = kwargs['timeout']
        stderr = (
            f'this command reached its {timeout}s timeout:\n '
            + subprocess.list2cmdline(args[0])
        )
        if not silent:
            error(stderr)

        res = subprocess.CompletedProcess(args[0], 1, stdout=stderr, stderr=stderr)

    stdout = res.stdout
    stderr = res.stderr
    if tee:
        stdout and echo(stdout)
        stderr and error(stderr)

    code = rc(res)
    if code:
        if check:
            if stdout or stderr:
                if tee:
                    # if tee, then it's already printed
                    context().exit(code)
                else:
                    echo(stdout)
                    error(stderr, exit=code)
            else:
                error(
                    f'command did not end well, and has empty output: {args}', exit=code
                )
        elif abort_on_fail:
            context().exit(code)

    return res


@lru_cache(maxsize=None)
def stern_version_challenge():
    try:
        version_res = subprocess_run(
            ['stern', '--version'],
            capture_output=True,
            env=ENV,
            check=True,
            silent=True,
        )
        version_str = version_res.stdout.decode('utf-8').split()[-1]
    except FileNotFoundError:
        download_stern()
        return stern_version_challenge()
    except PermissionError:
        error('Bad binary: stern, remove before use', exit=1)

    if version.parse(version_str) < STERN_MIN_VERSION:
        warn(f'your stern too old: {version_str}')
        download_stern()


def download_stern():
    platform = tell_platform()
    if platform == 'windows':
        error('choco install stern', exit=True)

    if platform == 'darwin':
        error('brew install stern', exit=True)

    if platform == 'linux':
        error('see https://github.com/wercker/stern', exit=True)


def stern(*args, check=True, **kwargs):
    stern_version_challenge()
    cmd = ['stern', *args]
    completed = subprocess_run(cmd, env=ENV, check=check, **kwargs)
    return completed


@lru_cache(maxsize=None)
def helm_version_challenge():
    try:
        version_res = subprocess_run(
            ['helm', 'version', '--short'],
            capture_output=True,
            env=ENV,
            check=True,
            silent=True,
        )
        version_str = version_res.stdout.decode('utf-8')
    except FileNotFoundError:
        download_helm()
        return helm_version_challenge()
    except PermissionError:
        error('Bad binary: helm, remove before use', exit=1)

    if version.parse(version_str) < HELM_MIN_VERSION:
        warn(f'your helm too old: {version_str}')
        download_helm()


def download_helm():
    error(f'you should install helm >= {HELM_MIN_VERSION}, for example:')
    platform = tell_platform()
    if platform == 'windows':
        error('choco install kubernetes-helm', exit=True)

    if platform == 'darwin':
        error('brew install helm', exit=True)

    if platform == 'linux':
        error('see https://github.com/helm/helm', exit=True)


def helm(*args, check=True, exit=False, **kwargs):
    helm_version_challenge()
    cmd = ['helm', *args]
    completed = subprocess_run(cmd, env=ENV, check=check, **kwargs)
    if exit:
        context().exit(rc(completed))

    return completed


def helm_delete(*args, exit=False):
    for release_name in args:
        res = helm('delete', release_name, check=False, capture_output=True)
        code = rc(res)
        if code:
            stderr = ensure_str(res.stderr)
            if 'not found' in stderr or 'already deleted' in stderr:
                echo(stderr)
            else:
                error(f'weird error during helm delete: {stderr}', exit=code)
        else:
            echo(res.stdout)

    if exit:
        ctx = context()
        ctx.exit(0)


def tell_release_image(release_name, revision=None, silent=False):
    revision_clause = [f'--revision={revision}'] if revision else []
    res = helm(
        'get',
        'values',
        release_name,
        *revision_clause,
        '-ojson',
        capture_output=True,
        check=not silent,
    )
    if silent and rc(res):
        return

    values = jalo(res.stdout)
    image_tag = values.get('imageTag')
    if image_tag:
        ctx = context()
        ctx.obj['image_tag'] = image_tag
        ctx.obj['git_revision'] = image_tag.split('-')[-1]

    return image_tag


def tell_cherry(git_revision=None, capture_output=True):
    if not git_revision:
        release_name = tell_release_name()
        deployed_image = tell_release_image(release_name)
        ctx = context()
        git_revision = ctx.obj.get('git_revision')
        if not git_revision:
            error(
                f'could not infer git revision from imageTag: {deployed_image}', exit=1
            )

    git_cherry = partial(
        git,
        'log',
        '--pretty=format:%ad: %s (%an)',
        '--date=short',
        '--invert-grep',
        '--grep',
        "^Merge",
        f'{git_revision}..HEAD',
    )
    if capture_output:
        res = git_cherry(capture_output=True, check=False)
        cherry = ensure_str(res.stdout or res.stderr)
        return cherry

    git_cherry()


def docker_images():
    res = docker('images', '--format', r'{{.Repository}}:{{.Tag}}', capture_output=True)
    local_images = ensure_str(res.stdout).splitlines()
    for image in local_images:
        repo, tag = image.split(':', 1)
        appname = repo.rsplit('/', 1)[-1]
        yield {
            'appname': appname,
            'image': image,
            'tag': tag,
        }


def docker(*args, exit=None, check=True, **kwargs):
    # to make tests easier, this function can run without context
    ctx = context(silent=True)
    if ctx and ctx.obj.get('remote_docker'):
        cc = tell_cluster_config()
        docker_host = cc.get('remote_docker')
        if docker_host:
            args = ['-H', docker_host] + list(args)

    cmd = ['docker', *args]
    completed = subprocess_run(cmd, check=check, **kwargs)
    if exit and ctx:
        ctx.exit(rc(completed))

    return completed


def parse_image_tag(image):
    try:
        repo, tag = image.split(':', 1)
    except (ValueError, AttributeError):
        error(f'not a valid image tag: {image}', exit=1)

    return repo, tag


def banyun(image, registry=None, overwrite_latest_tag=False, pull=False, exit=None):
    """搬运镜像到别人家里"""
    if registry and not isinstance(registry, str):
        loop = asyncio.new_event_loop()
        tasks = []
        for r in registry:
            future = loop.run_in_executor(
                None, banyun, image, r, overwrite_latest_tag, pull
            )
            tasks.append(future)

        loop.run_until_complete(asyncio.gather(*tasks))
        loop.close()
        return

    if isfile(image):
        res = docker('load', '-i', image, capture_output=True)
        image = ensure_str(res.stdout).strip().split()[-1]

    repo, tag = parse_image_tag(image)
    tag = tag.replace('release-', '')
    appname = repo.rsplit('/', 1)[-1]
    if not registry:
        cc = tell_cluster_config()
        registry = cc['registry']

    new_image = make_image_str(registry, appname, tag)
    if pull:
        docker('pull', image)

    docker('tag', image, new_image)
    docker('push', new_image, exit=exit)
    if overwrite_latest_tag:
        latest_image = make_image_str(registry, appname, 'latest')
        docker('tag', image, latest_image)
        docker('push', latest_image, exit=exit)

    if tag != 'prepare':
        echo(f' lain deploy --set imageTag={tag}', clean=False)

    return new_image


def docker_save_name(image):
    repo, tag = parse_image_tag(image)
    repo = repo.rsplit('/', 1)[-1]
    fname = f'{repo}_{tag}.tar.gz'
    return fname


def docker_save(image, output_dir, retag=None, force=False, pull=False, exit=False):
    if pull:
        docker('pull', image, capture_output=True)

    repo, tag = parse_image_tag(image)
    if retag:
        if retag in CLUSTERS:
            retag_cc = CLUSTERS[retag]
            registry = retag_cc['registry']
            appname = repo.rsplit('/', 1)[-1]
            new_image = make_image_str(registry, appname, tag)
        elif ':' in retag:
            new_image = retag
        else:
            new_image = f'{retag}:{tag}'

        docker('tag', image, new_image)
        image = new_image

    fname = docker_save_name(image)
    output_path = join(output_dir, fname)
    if isfile(output_path):
        if force:
            ensure_absent(output_path)
        else:
            warn(f'{output_path} already exists, use --force to overwrite')
            return

    res = docker(f'save {image} | gzip -c > {output_path}', shell=True)
    stderr = ensure_str(res.stderr)
    if stderr:
        error(stderr, exit=True)

    return output_path


def asdf(*args, exit=None, check=True, **kwargs):
    cmd = ['asdf', *args]
    completed = subprocess_run(cmd, env=ENV, check=check, **kwargs)
    if exit:
        context().exit(rc(completed))

    return completed


def has_asdf():
    try:
        res = asdf('--version', check=False, capture_output=True)
    except FileNotFoundError:
        return False
    if rc(res):
        error(f'weird asdf error: {res.stderr}')
        return False
    return True


def asdf_global(bin, v):
    cmd = ['global', bin, v]
    res = asdf(*cmd, check=False, capture_error=True)
    code = rc(res)
    if code:
        stderr = ensure_str(res.stderr)
        if 'is not installed' in stderr:
            asdf('install', bin, v)
            return asdf_global(bin, v)
        error(f'weird asdf error: {stderr}', exit=code)

    if not kubectl_version_challenge(autofix=False):
        cmd_str = ' '.join(cmd)
        error(f'kubectl version still do not match after asdf {cmd_str}')
        bad_bin = shutil.which('kubectl')
        error(f'you should probably delete {bad_bin}, let asdf manage for you', exit=1)


def git(*args, exit=None, check=True, **kwargs):
    cmd = ['git', *args]
    completed = subprocess_run(cmd, env=ENV, check=check, **kwargs)
    if exit:
        context().exit(rc(completed))

    return completed


def git_remote(**kwargs):
    cmd = ['git', 'remote', '-v']
    completed = subprocess_run(cmd, env=ENV, capture_output=True, check=True, **kwargs)
    output = ensure_str(completed.stdout)
    for line in output.splitlines():
        _, url, *_ = line.split()
        return url
    return ''


def try_to_label_nodes():
    ctx = context()
    appname = ctx.obj['appname']
    procs = ctx.obj['values']['procs']
    for proc_name, proc in procs.items():
        nodes = proc.get('nodes')
        if not nodes:
            continue
        label_name = f'{appname}-{proc_name}'
        kubectl('label', 'node', '--all', f'{label_name}-', '--overwrite')
        for node in nodes:
            kubectl('label', 'node', f'{node}', f'{label_name}=true', '--overwrite')


def tell_job_names(appname_prefix=True):
    values = load_helm_values()
    appname = values['appname']
    job_names = []
    for proc_name in values.get('jobs') or {}:
        job_name = f'{appname}-{proc_name}' if appname_prefix else proc_name
        job_names.append(job_name)

    return job_names


def try_to_print_job_logs():
    if job_names := tell_job_names(appname_prefix=False):
        for jn in job_names:
            lain_('logs', jn)


def try_to_cleanup_job(job_name=None):
    """when lain deploy, job may not be cleanup yet, so we cleanup manually"""
    if job_name:
        job_names = [job_name]
    else:
        job_names = tell_job_names()

    for jn in job_names:
        res = kubectl('delete', 'job', jn, capture_output=True, check=False)
        if rc(res):
            stderr = ensure_str(res.stderr)
            if 'not found' not in stderr:
                error(f'weird error when deleting job {jn}:')
                error(stderr, exit=1)


def fix_kubectl(cv=None, sv=None):
    if has_asdf():
        return asdf_global('kubectl', str(sv))
    error(
        f'you should not use kubectl {cv} for server version {sv}, this may cause problems, see https://kubernetes.io/docs/tasks/tools/#kubectl'
    )
    if tell_platform() != 'windows':
        warn('use asdf to manage kubectl: https://asdf-vm.com/')


@lru_cache(maxsize=None)
def kubectl_version_challenge(check=True, autofix=True):
    try:
        res = subprocess_run(
            ['kubectl', 'version', '--short'],
            capture_output=True,
            env=ENV,
            silent=True,
            check=check,
        )
        if rc(res):
            err = ensure_str(res.stderr).strip()
            error('kubectl version check failed:')
            error(f'{err}')
            return
        # https://kubernetes.io/releases/version-skew-policy/#kubectl
        cr, sr = ensure_str(res.stdout).splitlines()
        cv = version.parse(cr.rsplit(None, 1)[-1])
        # looks like v1.18.4-tke.13 / v1.20.4-aliyun.1
        sv = version.parse(sr.rsplit(None, 1)[-1].split('-', 1)[0])
    except FileNotFoundError:
        error('kubectl not found, trying to fix...')
        fix_kubectl()
        return kubectl_version_challenge()
    except PermissionError:
        error('Bad binary: kubectl, please reinstall', exit=1)

    if cv.major != sv.major or abs(sv.minor - cv.minor) >= 2:
        if autofix:
            fix_kubectl(cv, sv)
        else:
            return False

    return True


def kubectl(*args, exit=None, check=True, dry_run=False, **kwargs):
    kubectl_version_challenge(check=check)
    cmd = ['kubectl', *args]
    kwargs.setdefault('timeout', 20)
    completed = subprocess_run(cmd, env=ENV, check=check, dry_run=dry_run, **kwargs)
    if exit:
        context().exit(rc(completed))

    return completed


def get_pod_rc(pod_name, tries=5):
    while tries:
        tries -= 1
        res = kubectl(
            'get', 'po', pod_name, '-o=jsonpath={..exitCode}', capture_output=True
        )
        rc_str = ensure_str(res.stdout)
        if not rc_str:
            sleep(2)
            continue
        codes = [int(s) for s in rc_str.split()]
        return max(codes)

    error(f'cannot get exitCode for {pod_name}', exit=True)


def tell_release_name():
    ctx = context()
    values = ctx.obj.get('values') or {}
    return values.get('releaseName') or ctx.obj.get('appname')


def is_inside_cluster():
    return bool(ENV.get('KUBERNETES_SERVICE_HOST'))


def wait_for_svc_up(tries=20):
    release_name = tell_release_name()
    selector = f'helm.sh/chart={release_name}'
    res = kubectl(
        'get',
        'svc',
        '-l',
        selector,
        '--no-headers=true',
        capture_output=True,
        check=False,
    )
    svc_urls = []
    for line in ensure_str(res.stdout).splitlines():
        svc_name, _, _, _, port, _ = line.split()
        portnum = int(port.split('/', 1)[0])
        svc_urls.append(f'http://{svc_name}:{portnum}')

    def test_urls(urls):
        for url in svc_urls:
            try:
                requests.get(url, timeout=1)
            except Exception as e:
                warn(f'{url} not up due to {e}')
                return False

        return True

    while tries:
        tries -= 1
        sleep(3)
        if test_urls(svc_urls):
            return True

    return False


def get_youngest_pod_ages(selector=None):
    res = kubectl(
        'get',
        'po',
        '-l',
        selector,
        '--no-headers=true',
        capture_output=True,
    )
    ages = []
    podlines = ensure_str(res.stdout).splitlines()
    for podline in podlines:
        _, _, _, _, age, *_ = parse_podline(podline)
        ages.append(parse_multi_timespan(age))

    return min(ages)


def wait_for_pod_up(selector=None, tries=40):
    if not selector:
        ctx = context()
        appname = ctx.obj['appname']
        selector = f'app.kubernetes.io/name={appname}'

    bad_state = frozenset(('imagepullbackoff',))
    waiting_state = frozenset(
        ('pending', 'containercreating', 'notready', 'terminating')
    )
    while tries:
        tries -= 1
        sleep(3)
        res = kubectl(
            'get',
            'po',
            '-l',
            selector,
            '--no-headers=true',
            capture_output=True,
            check=False,
        )
        stdout = ensure_str(res.stdout)
        pod_lines = stdout.splitlines()
        current_states = set()
        pod_names = []
        for line in pod_lines:
            debug(line)
            pod_name, ready_pair, state, *_ = line.split()
            state = state.lower()
            if state == 'running':
                n_ready, n_all = ready_pair.split('/')
                if n_ready != n_all:
                    state = 'notready'

            current_states.add(state.lower())
            pod_names.append(pod_name)

        if current_states.intersection(bad_state):
            error(f'pod in bad state:\n{stdout}', exit=1)

        if not current_states.intersection(waiting_state):
            return pod_names
        debug(stdout)
        continue
    error('job container never got up, here\'s what\'s wrong:')
    kubectl('describe', 'po', pod_name, check=False)
    kubectl('logs', pod_name, check=False)


def wait_for_cluster_up(tries=1):
    context().obj['silent'] = True
    cc = tell_cluster_config()
    domain_suffix = tell_domain_suffix(cc)
    url = f'http://default-backend{domain_suffix}'
    probe_result = None
    forgive_error_substrings = (
        'timeout',
        'unable to connect',
        'was refused',
        'context deadline exceeded',
    )
    while tries:
        tries -= 1
        res = kubectl('version', capture_output=True, timeout=2, check=False)
        stderr = ensure_str(res.stderr).lower()
        if not stderr:
            # 如果是托管集群的话, master 始终在线, k version 的输出并不足以证明该集群
            # worker 节点都启动了, 所以还得验证下 ingress controller 是不是在线
            with suppress(RequestException):
                probe_result = requests.get(url)

            if probe_result is not None and probe_result.status_code == 404:
                return 'on'
            probe_msg = probe_result is not None and probe_result.text
            debug(f'cluster not up due to probe failed: {probe_msg}')
            sleep(3)
            continue
        if any(s in stderr for s in forgive_error_substrings):
            # 等开机, 多等会吧
            sleep(5)
            continue
        error(f'weird error {stderr}', exit=True)


def tell_machine():
    machine = platform.machine()
    if machine in {'amd64', 'x86_64'}:
        return 'amd64'
    if machine in {'arm64', 'aarch64'}:
        return 'arm64'
    raise ValueError(
        f'Sorry, never seen this machine: {machine}. Use arm64 or amd64 for lain'
    )


def tell_platform():
    platform_ = sys.platform
    if platform_.startswith('darwin'):
        return 'darwin'
    if platform_.startswith('linux'):
        return 'linux'
    if platform_.startswith('win'):
        return 'windows'
    raise ValueError(
        f'Sorry, never seen this platform: {platform_}. Use a Mac / Linux / Windows for lain'
    )


def ensure_absent(path, preserve=None):
    """delete files, can optionally ignore some files using preserve"""
    if not isinstance(path, str):
        for p in path:
            ensure_absent(p, preserve=preserve)

        return

    if isinstance(preserve, str):
        preserve = [preserve]

    if preserve:
        d = TemporaryDirectory()
        for p in preserve:
            if not exists(p):
                continue
            temp_path = join(d.name, p)
            makedirs(dirname(temp_path))
            shutil.move(p, temp_path)

    if isdir(path):
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass
    else:
        try:
            remove(path)
        except FileNotFoundError:
            pass

    if preserve:
        for p in preserve:
            temp_path = join(d.name, p)
            if not exists(temp_path):
                continue
            makedirs(dirname(p))
            shutil.move(temp_path, p)

        d.cleanup()


def find(path):
    """mimic to GNU find"""
    for currentpath, _, files in os.walk(path):
        for file in files:
            abs_path = join(currentpath, file)
            relpath = os.path.relpath(abs_path, path)
            yield relpath


def edit_file(f):
    """
    Args:
        f (str): file path.
    """
    subprocess.call([ENV.get('EDITOR', 'vim'), f], env=os.environ)


def yalo(f, many=False):
    if hasattr(f, 'read'):
        f.seek(0)
        content = f.read()

    # tempfile buffer content could be different from the actual disk file
    if hasattr(f, 'name'):
        with open(f.name) as file_again:
            content = file_again.read()
    elif isfile(f):
        with open(f) as file_:
            content = file_.read()
    else:
        content = f

    load = yaml.load_all if many else yaml.load
    return load(content)


def yadu(dic, f=None):
    if not f:
        buf = BytesIO()
        yaml.dump(dic, buf)
        return ensure_str(buf.getvalue())
    if hasattr(f, 'read'):
        yaml.dump(dic, f)
    elif isinstance(f, str):
        with open(f, 'wb') as dest:
            yaml.dump(dic, dest)
    elif isinstance(f, int):
        with fdopen(f, 'wb') as dest:
            yaml.dump(dic, dest)
    else:
        raise ValueError(f'f must be a file or path, got {f}')


def jadu(dic):
    return json.dumps(dic, separators=(',', ':'))


def jalo(s):
    """stupid json doesn't even tell you why anything fails"""
    try:
        return json.loads(s)
    except ValueError as e:
        raise ValueError(f'cannot decode: {ensure_str(s)}') from e


def tell_screen_height(scale):
    lines = shutil.get_terminal_size().lines
    return int(lines * scale)


def tell_screen_width(scale):
    cols = shutil.get_terminal_size().columns
    return max([88, int(cols * scale)])


def brief(s):
    r"""
    >>> a = '''
    ... foo
    ... bar
    ... '''
    >>> brief(a)
    '\\nfoo\\nbar\\n'
    """
    try:
        single_line = s.encode('unicode_escape')
    except AttributeError:
        return s
    width = tell_screen_width(0.5)
    if len(single_line) > width:
        single_line = single_line[:width] + b'...'

    return single_line.decode('utf-8')


RESERVED_WORDS = set()


class ReserveWord(SchemaMeta):
    """collect reserved words"""

    def __new__(mcs, name, bases, attrs):
        for fname, field in attrs.items():
            if isinstance(field, Field):
                RESERVED_WORDS.add(fname)

        return super().__new__(mcs, name, bases, attrs)


ReservedWord = NoneOf(RESERVED_WORDS, error='this is a reserved word, please change')


class LenientSchema(Schema, metaclass=ReserveWord):
    class Meta:
        unknown = INCLUDE


class PrepareSchema(LenientSchema):
    script = List(Str, required=True)
    keep = List(Str, load_default=[])

    @post_load
    def finalize(self, data, **kwargs):
        keep = data.setdefault('keep', [])
        for i, k in enumerate(keep):
            if '*' in k:
                raise ValidationError(f'keep item should not contain "*", got: {k}')
            if k.startswith('/'):
                raise ValidationError(f'keep item should not be abs path, got: {k}')
            if not k.startswith('./'):
                keep[i] = f'./{k}'

        return data


class BuildSchema(LenientSchema):
    base = Str(required=True)
    prepare = Nested(PrepareSchema, required=False, allow_none=True)
    script = List(Str, load_default=[])
    workdir = Str(load_default=DEFAULT_WORKDIR, allow_none=False)


def parse_copy(stuff):
    """
    >>> parse_copy('/path')
    {'src': '/path', 'dest': '/path'}
    >>> parse_copy({'src': '/path'})
    {'src': '/path', 'dest': '/path'}
    >>> parse_copy({'src': '/path', 'dest': '/another'})
    {'src': '/path', 'dest': '/another'}
    """
    if isinstance(stuff, str):
        return {'src': stuff, 'dest': stuff}
    if isinstance(stuff, dict):
        if 'src' not in stuff:
            raise ValidationError('if copy clause is a dict, it must contain src')
        if 'dest' not in stuff:
            stuff['dest'] = stuff['src']

        return stuff
    raise ValidationError(f'copy clause must be str or dict, got {stuff}')


class ReleaseSchema(LenientSchema):
    script = List(Str, load_default=[])
    workdir = Str(load_default=DEFAULT_WORKDIR)
    dest_base = Str()
    copy = List(Function(deserialize=parse_copy), load_default=[])


class VolumeMountSchema(LenientSchema):
    mountPath = Str(required=True)
    subPath = Str(required=False)

    @validates("subPath")
    def validate_subPath(self, value):
        bn = basename(value)
        if bn != value:
            raise ValidationError(f'subPath should be {bn}, not {value}')


class HPASchema(LenientSchema):
    @post_load
    def finalize(self, data, **kwargs):
        if 'targetCPUUtilizationPercentage' in data:
            raise ValidationError(
                'you should remove targetCPUUtilizationPercentage from hpa, and use hpa.metrics'
            )
        return data


class ResourceSchema(Schema):
    cpu = Raw(required=True)
    memory = Raw(required=True)


class ResourcesSchema(Schema):
    requests = Nested(ResourceSchema, required=True)
    limits = Nested(ResourceSchema, required=True)


# env 的 key, value 必须是字符串, 否则 helm 会转为科学记数法
# https://github.com/helm/helm/issues/6867
env_schema = Dict(keys=Str(), values=Str(), allow_none=True)


class InitContainerSchema(LenientSchema):
    env = env_schema


class DeploymentSchema(LenientSchema):
    env = env_schema
    hpa = Nested(HPASchema, required=False)
    containerPort = Int(required=False)
    readinessProbe = Raw(load_default={})
    replicaCount = Int(required=True)
    resources = Nested(ResourcesSchema, required=True)

    @post_load
    def finalize(self, data, **kwargs):
        if 'containerPort' in data and 'readinessProbe' not in data:
            raise ValidationError(
                'when containerPort is defined, you must use readinessProbe as well'
            )
        return data


class JobSchema(LenientSchema):
    env = env_schema
    initContainers = List(Nested(InitContainerSchema))


class CronjobSchema(LenientSchema):
    resources = Nested(ResourcesSchema, required=False)
    env = env_schema


class IngressSchema(LenientSchema):
    host = Str(required=True)
    deployName = Str(required=True)
    paths = List(Str, required=True)


def get_hosts_dict():
    hosts_dic = defaultdict(set)
    with open('/etc/hosts') as f:
        content = f.read()
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            ip, *hosts = line.split()
            hosts_dic[ip].update(set(hosts))

    return hosts_dic


class HostAliasSchema(Schema):
    ip = Str(required=True)
    hostnames = List(Str, required=True)


class ClusterConfigSchema(LenientSchema):
    domain = Str(load_default='', allow_none=False)
    domain_suffix = Str(load_default='', allow_none=False)
    extra_docs = Str()
    secrets_env = Dict(keys=Str(), values=Raw(), required=False, allow_none=True)
    hostAliases = List(Nested(HostAliasSchema), required=False)

    @post_load
    def finalize(self, data, **kwargs):
        if 'extra_docs' in data:
            data['extra_docs'] = data['extra_docs'].strip()

        if self.context.get('is_current', False):
            # only read secrets env when dealing with the current cluster
            secrets_env = data.pop('secrets_env', None) or {}
            for dest, env in secrets_env.items():
                if isinstance(env, str):
                    env_name = env
                    hint = ''
                else:
                    env_name = env['env_name']
                    hint = env['hint']

                if env_name not in ENV:
                    error(
                        f'environment variable {env_name} is missing, hint: {hint}',
                        exit=1,
                    )
                else:
                    data[dest] = ENV[env_name]

        return data


class HelmValuesSchema(LenientSchema):
    """app config lies in chart/values.yaml, all config can be overridden in
    chart/values.yaml or chart/values-[CLUSTER].yaml
    """

    # app config goes here
    appname = Str(validate=ReservedWord, required=True)
    releaseName = Str(validate=ReservedWord, required=False)
    env = env_schema
    volumeMounts = List(Nested(VolumeMountSchema), allow_none=True)
    deployments = deploy = deployment = Dict(
        keys=Str(validate=ReservedWord),
        values=Nested(DeploymentSchema),
        required=False,
        allow_none=True,
    )
    jobs = job = Dict(
        keys=Str(validate=ReservedWord),
        values=Nested(JobSchema),
        required=False,
        allow_none=True,
    )
    cronjobs = cronjob = Dict(
        keys=Str(validate=ReservedWord),
        values=Nested(CronjobSchema),
        required=False,
        allow_none=True,
    )
    statefulSets = statefulSet = statefulset = sts = Dict(
        keys=Str(validate=ReservedWord), values=Raw(), required=False, allow_none=True
    )
    tests = Dict(
        keys=Str(validate=ReservedWord), values=Raw, required=False, allow_none=True
    )
    ingresses = ingress = ing = List(
        Nested(IngressSchema), required=False, allow_none=True
    )
    externalIngresses = externalIngress = externalIng = List(
        Nested(IngressSchema), required=False
    )
    canaryGroups = Dict(
        keys=Str(),
        values=Dict(keys=Str(validate=OneOf(INGRESS_CANARY_ANNOTATIONS)), values=Str()),
        required=False,
        allow_none=True,
        load_default=None,
    )
    build = Nested(BuildSchema, required=False)
    release = Nested(ReleaseSchema, required=False)

    @staticmethod
    def merge_aliases(data, key, aliases=()):
        dic = data.setdefault(key, {}) or {}
        for alias in aliases:
            recursive_update(dic, data.get(alias, {}) or {})

    @post_load
    def finalize(self, data, **kwargs):
        self.merge_aliases(data, 'deployments', aliases=('deploy', 'deployment'))
        self.merge_aliases(data, 'cronjobs', aliases=['cronjob'])
        self.merge_aliases(
            data, 'statefulSets', aliases=['sts', 'statefulSet', 'statefulset']
        )
        for k in ['deployments', 'cronjobs', 'statefulSets', 'tests']:
            if not data.get(k):
                data[k] = {}

        data['procs'] = data['deployments'].copy()
        data['procs'].update(data['cronjobs'])
        data['procs'].update(data['statefulSets'])
        # check for duplicate proc names
        deploy_names = set(data['deployments'] or [])
        cronjob_names = set(data['cronjobs'] or [])
        sts_names = set(data['statefulSets'] or [])
        duplicated_names = [
            deploy_names.intersection(cronjob_names),
            deploy_names.intersection(sts_names),
            cronjob_names.intersection(sts_names),
        ]
        if any(duplicated_names):
            raise ValidationError(
                f'proc names should not duplicate: {duplicated_names}'
            )
        release_clause = data.get('release')
        if release_clause:
            build_clause = data.get('build')
            if not build_clause:
                raise ValidationError('release defined, but not build')
            release_clause.setdefault('dest_base', build_clause['base'])

        return data


def validate_proc_name(ctx, param, value):
    if not value:
        return value
    ctx = context()
    procs = ctx.obj['values']['procs']
    if value not in procs:
        proc_names = list(procs)
        raise BadParameter(f'{value} not found in procs, choose from {proc_names}')
    return value


def update_extra_values(values, cluster=None, ignore_extra=False):
    internal_values_file = tell_cluster_values_file(cluster=cluster, internal=True)
    if internal_values_file:
        recursive_update(
            values,
            yalo(open(internal_values_file)),
            ignore_extra=ignore_extra,
        )

    cluster_values_file = tell_cluster_values_file(cluster=cluster)
    ctx = context(silent=True)
    if cluster_values_file:
        dic = yalo(open(cluster_values_file))
        if not isinstance(dic, dict):
            # 调用 gitlab 接口对 link 类型的文件处理有问题, 下载下来以后只是一个普通的文本文件
            # 只好在代码里实现一下 link 咯
            if isinstance(dic, str) and isfile(join(CHART_DIR_NAME, dic)):
                linked_file = join(CHART_DIR_NAME, dic)
                dic = yalo(open(linked_file))
            else:
                error(
                    f'content of cluster values file {cluster_values_file} is neither a dict or a valid values path, got: {dic}',
                    exit=1,
                )

        if ctx:
            ctx.obj['cluster_values'] = dic

        try:
            recursive_update(
                values, dic, ignore_extra=ignore_extra, prevent_duplication=True
            )
        except DuplicationInValues as e:
            error(f'duplication detected in {cluster_values_file}')
            error(f'{e}')
            error('you must eliminate all duplications before proceed', exit=1)

    extra_values_file = ctx and ctx.obj.get('extra_values_file')
    if extra_values_file:
        extra_values = yalo(extra_values_file)
        recursive_update(values, extra_values, ignore_extra=ignore_extra)
        if ctx:
            ctx.obj['extra_values'] = extra_values


def load_helm_values(values_yaml=f'./{CHART_DIR_NAME}/values.yaml'):
    if hasattr(values_yaml, 'read'):
        values = yalo(values_yaml)
    else:
        with open(values_yaml) as f:
            values = yalo(f)

    update_extra_values(values)
    schema = HelmValuesSchema()
    try:
        loaded = schema.load(values)
    except ValidationError as e:
        error('your values.yaml did not pass schema check:')
        error(e, exit=1)

    return loaded


def ensure_helm_initiated():
    """gather basic information about the current app.
    If cluster info is provided, will try to fetch app status from Kubernetes"""
    with suppress(OSError):
        tell_cluster()

    lookout_env = LOOKOUT_ENV.intersection(ENV)
    if lookout_env:
        warn(f'you better unset these variables: {lookout_env}')

    ctx = context()
    obj = ctx.obj
    obj['chart_name'] = CHART_DIR_NAME
    obj['chart_version'] = CHART_VERSION
    values_yaml = f'./{CHART_DIR_NAME}/values.yaml'
    try:
        values = load_helm_values(values_yaml)
        appname = obj['appname'] = values['appname']
        obj['values'] = values
        obj['secret_name'] = f'{appname}-secret'
        obj['env_name'] = f'{appname}-env'
    except FileNotFoundError:
        warn('not in a lain app repo')
        raise
    except KeyError as e:
        error(e)
        error(
            f'{values_yaml} doesn\'t look like a valid lain4 yaml, if you want to use lain4 for this app, use `lain inif -f`'
        )
        raise
    # collect all uppercase consts
    for k, v in globals().items():
        if k.isupper() and not k.startswith('_'):
            if k in obj:
                continue
            obj[k] = v

    obj['urls'] = tell_ingress_urls()


def helm_status(release_name):
    res = helm('status', release_name, '-o', 'json', capture_output=True, check=False)
    code = rc(res)
    if not code:
        son = jalo(res.stdout)
        if son['info']['status'] == 'uninstalled':
            return
        return son
    stderr = res.stderr.decode('utf-8')
    # 'not found' is the only error we can safely ignore
    if 'not found' not in stderr:
        error('helm error during getting app status:')
        error(stderr, exit=code)


template_env.filters['basename'] = basename
template_env.filters['quote'] = quote
template_env.filters['to_yaml'] = yadu
template_env.filters['to_json'] = jadu
template_env.filters['brief'] = brief


class KVPairType(click.ParamType):
    name = "kvpair"

    def convert(self, value, param, ctx):
        try:
            k, v = value.split('=')
            return (k, v)
        except (AttributeError, ValueError):
            self.fail(
                "expected something like FOO=BAR, got "
                f"{value!r} of type {type(value).__name__}",
                param,
                ctx,
            )


def is_values_file(fname):
    """
    >>> is_values_file('foo/bar/values.yaml')
    True
    >>> is_values_file('values.yaml.j2')
    True
    >>> is_values_file('values-future.yaml')
    True
    >>> is_values_file('values-future.yml')
    True
    >>> is_values_file('deployment.yml.j2')
    False
    """
    fname = basename(fname)
    fname = re.sub(r'\.j2', '', fname)
    fname = re.sub(r'.yml', '.yaml', fname)
    is_yaml = fname.endswith('yaml')
    is_values = fname.startswith('values')
    return is_yaml and is_values


def top_procs(appname):
    """use memory data from prometheus as memory_top"""
    result = {}
    cc = tell_cluster_config()
    values = context().obj['values']
    if 'prometheus' in cc:
        from lain_cli.prometheus import Prometheus

        prometheus = Prometheus()
    else:
        return result
    for proc_name, proc in values['procs'].items():
        memory_top = prometheus.memory_quantile(appname, proc_name)
        if not memory_top:
            continue
        # container memory shoudn't be lower than 4Mi
        memory_top = max(memory_top, KUBERNETES_MIN_MEMORY)
        memory_top_str = format_kubernetes_memory(memory_top)
        cpu_top, accurate = prometheus.cpu_p95(appname, proc_name)
        if not accurate:
            continue
        proc.update(
            {
                'memory_top': memory_top,
                'memory_top_str': memory_top_str,
                'cpu_top': cpu_top,
            }
        )
        result[proc_name] = proc

    return result


KUBERNETES_DISK_SIZE_UNITS = (
    CombinedUnit(
        SizeUnit(1000**2, 'MB', 'megabyte'), SizeUnit(1024**2, 'Mi', 'mebibyte')
    ),
)


def pluralize_compact(count, singular, plural=None):
    if not plural:
        plural = singular + 's'
    return f'{count}{singular if math.floor(float(count)) == 1 else plural}'


def format_kubernetes_memory(num_bytes):
    for unit in reversed(KUBERNETES_DISK_SIZE_UNITS):
        if num_bytes >= unit.binary.divider:
            number = round_number(
                math.ceil(float(num_bytes) / unit.binary.divider), keep_width=False
            )
            return pluralize_compact(number, unit.binary.symbol, unit.binary.symbol)
    debug(f'value too small, format as 50M instead: {num_bytes}')
    return '50M'


def parse_kubernetes_cpu(s):
    """
    https://kubernetes.io/docs/concepts/configuration/manage-compute-resources-container/#meaning-of-cpu
    >>> parse_kubernetes_cpu('1000m')
    1000
    >>> parse_kubernetes_cpu('1')
    1000
    >>> parse_kubernetes_cpu(0.5)
    500
    >>> parse_kubernetes_cpu(1)
    1000
    """
    if isinstance(s, Number):
        return int(s * 1000)
    if isinstance(s, str) and s.endswith('m'):
        return int(s.replace('m', ''))
    if isinstance(s, str) and s.isdigit():
        return parse_kubernetes_cpu(float(s))
    raise ValueError(f'weird cpu value: {s}')


@contextmanager
def change_dir(d):
    saved_dir = cwd()
    try:
        os.chdir(d or '.')
        yield
    finally:
        os.chdir(saved_dir)


def try_lain_prepare(keep_dockerfile=False):
    """想尽办法拿到 prepare 镜像, 先 pull, 没有的话看本地,
    本地有的话还要顺手搬运过去"""
    ctx = context()
    values = ctx.obj['values']
    build_clause = values['build']
    prepare_clause = build_clause.get('prepare')
    if not prepare_clause:
        return

    appname = ctx.obj['appname']
    local_prepare_image = ''
    for image_info in docker_images():
        if image_info['appname'] == appname and image_info['tag'] == 'prepare':
            local_prepare_image = image_info['image']
            break

    prepare_image = lain_image(stage='prepare')
    res = docker('pull', prepare_image, capture_error=True, check=False)
    returncode = rc(res)
    if returncode:
        stderr = ensure_str(res.stderr)
        if 'not found' in stderr:
            if local_prepare_image:
                echo(
                    f'{prepare_image} not found, will publish {local_prepare_image} to {prepare_image}'
                )
                banyun(local_prepare_image)
            else:
                lain_build(stage='prepare', push=True, keep_dockerfile=keep_dockerfile)
        else:
            error(stderr, exit=returncode)


def tell_git_ignore():
    try:
        with open(GITIGNORE_NAME) as f:
            return f.read()
    except FileNotFoundError:
        warn(
            f'{GITIGNORE_NAME} not found, consider creating one. if .gitignore is in somewhere else, make a soft link'
        )
        return ''


def make_docker_ignore():
    template = template_env.get_template('.dockerignore.j2')
    git_ignore = tell_git_ignore()
    converted = []
    # https://github.com/LinusU/gitignore-to-dockerignore/blob/master/index.js
    for line in git_ignore.splitlines():
        ig = line.strip()
        if not ig or ig.startswith('#'):
            continue
        if ig.startswith('!/'):
            converted.append('!' + ig[2:])
        elif ig.startswith('!'):
            converted.append('!**/' + ig[1:])
        elif ig.startswith('/'):
            converted.append(ig[1:])
        else:
            converted.append('**/' + ig)

    with open(DOCKERIGNORE_NAME, 'w') as f:
        f.write(template.render(git_ignores=converted))


def lain_build(stage='build', push=True, keep_dockerfile=False):
    ctx = context()
    ctx.obj['current_build_stage'] = stage
    values = ctx.obj['values']
    if 'build' not in values:
        warn('build not defined in {CHART_DIR_NAME}/values.yaml', exit=0)

    build_clause = values['build']
    prepare_clause = build_clause.get('prepare')
    if stage == 'prepare' and not prepare_clause:
        build_yaml = yadu(build_clause)
        warn(f'empty prepare clause:\n\n{build_yaml}', exit=0)

    image = lain_image(stage)
    template = template_env.get_template(f'{DOCKERFILE_NAME}.j2')
    if isfile(DOCKERFILE_NAME):
        error(
            f'{DOCKERFILE_NAME} already exists, remove if you want to use lain build',
            exit=True,
        )

    if isfile(DOCKERIGNORE_NAME):
        dockerignore_created = False
        warn(f'you have your own {DOCKERIGNORE_NAME}, fine')
    else:
        make_docker_ignore()
        dockerignore_created = True

    with open(DOCKERFILE_NAME, 'w') as f:
        f.write(template.render(**ctx.obj))

    try:
        docker(
            'build',
            '--pull',
            '-t',
            image,
            '--target',
            stage,
            '-f',
            DOCKERFILE_NAME,
            '.',
            check=False,
            abort_on_fail=True,
        )
    finally:
        if not keep_dockerfile:
            ensure_absent(DOCKERFILE_NAME)

        if dockerignore_created:
            ensure_absent(DOCKERIGNORE_NAME)

    if push:
        banyun(image)

    return image


def make_wildcard_domain(d):
    """
    >>> make_wildcard_domain('foo-bar.example.com')
    ['*.example.com', 'example.com']
    """
    if d.count('.') == 1:
        without_star = d
        with_star = f'*.{without_star}'
    else:
        with_star = re.sub(r'^([^.]+)(?=.)', '*', d, 1)
        without_star = with_star.replace('*.', '')

    return [with_star, without_star]


def make_image_str(registry=None, appname=None, image_tag=None):
    if not registry:
        cc = tell_cluster_config()
        registry = cc['registry']

    if not image_tag:
        image_tag = lain_meta()

    if not appname:
        ctx = context()
        appname = ctx.obj['appname']

    if registry.startswith('docker.io'):
        # omit default registry
        registry = registry.replace('docker.io/', '')

    image = f'{registry}/{appname}:{image_tag}'
    return image


def tell_image():
    ctx = context()
    appname = ctx.obj.get('appname')
    meta = lain_meta()
    for image_info in docker_images():
        if image_info['appname'] == appname and image_info['tag'] == meta:
            return image_info['image']


def tell_domain_tls_name(d):
    """
    >>> tell_domain_tls_name('*.example.com')
    'example-com'
    >>> tell_domain_tls_name('prometheus.example.com')
    'prometheus-example-com'
    """
    parts = d.split('.')
    if parts[0] == '*':
        parts = parts[1:]

    return '-'.join(parts)


def rc(res):
    try:
        return res.exit_code
    except AttributeError:
        return res.returncode


def stable_hash(s):
    h = blake2b(digest_size=8, key=b'lain')
    h.update(s.encode('utf-8'))
    return h.hexdigest()


def make_job_name(command):
    if not command:
        command = ''

    if not isinstance(command, str):
        command = ''.join(command)

    ctx = context()
    appname = ctx.obj['appname']
    h = stable_hash(command)
    job_name = f'{appname}-{h}'
    return job_name


def version_challenge():
    ctx = context()
    if ctx.obj['ignore_lint']:
        return
    session = PipSession()
    session.timeout = 2
    cc = tell_cluster_config()
    if not cc:
        return
    pypi_index = cc['pypi_index']
    search_scope = SearchScope.create(find_links=[], index_urls=[pypi_index])
    link_collector = LinkCollector(session=session, search_scope=search_scope)
    selection_prefs = SelectionPreferences(
        allow_yanked=False,
        allow_all_prereleases=False,
    )
    finder = PackageFinder.create(
        link_collector=link_collector,
        selection_prefs=selection_prefs,
        use_deprecated_html5lib=False,
    )
    best_candidate = finder.find_best_candidate('lain_cli').best_candidate
    debug(f'best candidate: {best_candidate}')
    if not best_candidate:
        warn(f'fail to lookup latest version from {pypi_index}')
        return
    now = version.parse(__version__)
    new = best_candidate.version
    if any([now.major > new.major, now.minor > new.minor]):
        return
    if not all(
        [now.major == new.major, now.minor == new.minor, new.micro - now.micro <= 2]
    ):
        error(f'you are using lain_cli=={__version__}, upgrade before use:')
        extra_index = cc.get('pypi_extra_index')
        if extra_index:
            extra_clause = f'--extra-index-url {extra_index}'
        else:
            extra_clause = ''

        error('workon lain-cli')
        error(f'pip install -U lain_cli=={new} -i {pypi_index} {extra_clause}')
        error('you can use --ignore-lint to bypass this check', exit=1)


def user_challenge(release_name):
    """用户必须与 helm values 记载的 user 匹配, 才能继续"""
    res = helm('get', 'values', release_name, '-ojson', capture_output=True)
    values = jalo(res.stdout)
    written_user = values.get('user')
    if not written_user:
        return
    user = tell_executor()
    if written_user != user:
        error(
            f'{release_name} was deployed by {written_user}, not to be tampered by {user}',
            exit=1,
        )


def build_jit_challenge(image_tag):
    if image_tag == 'latest':
        return True
    ctx = context()
    if not ctx.obj.get('build_jit'):
        return True
    lain_meta_ = lain_meta()
    if image_tag == lain_meta_:
        return True
    error('when using lain deploy, do not use --build with --set imageTag=xxx', exit=1)


def get_parent_pid_name():
    pid = getppid()
    process = psutil.Process(pid)
    return process.name()


def called_by_sh():
    pname = get_parent_pid_name()
    if pname.endswith('sh'):
        return True
    return False


def tell_cluster(silent=False):
    """
    有这样一个副作用, 就是写好了 ctx.obj['cluster']
    helm values 必须要在一个 lain4 项目 repo 下才会有
    但是少数功能不需要在 repo 下也可以执行
    """
    link = join(KUBECONFIG_DIR, 'config')
    try:
        kubeconfig_file = readlink(link)
    except OSError:
        error(f'{link} is not a symlink or does not exist')
        if silent:
            return
        raise

    name = basename(kubeconfig_file)
    cluster_name = name.split('-', 1)[-1]
    ctx = context(silent=True)
    if ctx:
        ctx.obj['cluster'] = cluster_name

    return cluster_name


def tell_cluster_values_file(cluster=None, internal=False):
    """internal cluster values resides in lain4 package data, while app can
    define cluster values of their own"""
    if not cluster:
        cluster = tell_cluster()

    d = CLUSTER_VALUES_DIR if internal else CHART_DIR_NAME
    values_file = join(d, f'values-{cluster}.yaml')
    if isfile(values_file):
        return values_file


def tell_cluster_config(cluster=None, is_current=None):
    ctx = context(silent=True)
    if not cluster:
        if ctx:
            if 'cluster_config' in ctx.obj:
                return ctx.obj['cluster_config']
            cluster = ctx.obj['cluster']
        else:
            cluster = tell_cluster()

    values_file = tell_cluster_values_file(cluster=cluster, internal=True)
    if not values_file:
        warn(f'cluster values not found for {cluster} inside {CLUSTER_VALUES_DIR}')
        return {}

    if is_current is None:
        try:
            is_current = tell_cluster() == cluster
        except OSError:
            is_current = False

    data = yalo(open(values_file))
    # cluster values can be overriden in values.yaml
    update_extra_values(data, cluster=cluster, ignore_extra=True)
    schema = ClusterConfigSchema(context={'is_current': is_current})
    try:
        cc = schema.load(data)
    except ValidationError as e:
        error('your cluster config did not pass schema check:')
        error(e, exit=1)

    if is_current:
        if ctx:
            ctx.obj['cluster_config'] = cc

        host_aliases = cc.get('hostAliases', []) or []
        if host_aliases:
            hosts_dic = get_hosts_dict()
            for h in host_aliases:
                ip = h['ip']
                existing_names = hosts_dic[ip]
                for name in h['hostnames']:
                    if name not in existing_names:
                        error(f'you should add this to /etc/hosts: {ip} {name}')

    return cc


def tell_all_clusters():
    ccs = {}
    argv = sys.argv
    wanted_cluster = None
    if len(argv) == 3 and argv[1] == 'use' and argv[0].rsplit('/', 1)[-1] == 'lain':
        wanted_cluster = argv[-1]
    else:
        with suppress(OSError):
            wanted_cluster = tell_cluster()

    for f in glob(join(KUBECONFIG_DIR, '*')):
        if not isfile(f):
            continue
        fname = basename(f)
        if not fname.startswith('kubeconfig-'):
            continue
        cluster_name = fname.split('-', 1)[-1]
        is_current = cluster_name == wanted_cluster
        cc = tell_cluster_config(cluster_name, is_current=is_current)
        if not cc:
            continue
        ccs[cluster_name] = cc

    if not ccs:
        error('no cluster values found at all, you should first set things up')

    for f in glob(join(CLUSTER_VALUES_DIR, 'values-*')):
        fname = basename(f)
        cluster_name = fname.split('-', 1)[-1].split('.', 1)[0]
        if cluster_name not in ccs:
            warn(
                f'~/.kube/kubeconfig-{cluster_name} not found, you should get it from your system administrator'
            )

    return ccs


def lain_docs(path):
    cc = tell_cluster_config()
    sphinx_docs_url = (
        cc.get('sphinx_docs_url') or 'https://lain-cli.readthedocs.io/en/latest'
    )
    url = join(sphinx_docs_url, path)
    return url


CLUSTERS = tell_all_clusters()
