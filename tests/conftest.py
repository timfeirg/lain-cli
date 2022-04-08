import sys
import traceback
from os import chdir, environ, getcwd
from os.path import abspath, dirname, join
from random import choice
from string import ascii_letters
from typing import Any, Tuple

import click
import pytest
from click.testing import CliRunner

from lain_cli.lain import lain
from lain_cli.utils import (
    yadu,
    CHART_DIR_NAME,
    CLUSTERS,
    DOCKERFILE_NAME,
    DOCKERIGNORE_NAME,
    GITIGNORE_NAME,
    change_dir,
    ensure_absent,
    ensure_helm_initiated,
    error,
    helm,
    kubectl,
    lain_meta,
    make_canary_name,
    rc,
    tell_cluster_config,
    tell_registry_client,
    yalo,
)

TESTS_BASE_DIR = dirname(abspath(__file__))
DUMMY_APPNAME = 'dummy'
DUMMY_OVERRIDE_RELEASE_NAME = 'ymmud'
DUMMY_CANARY_NAME = make_canary_name(DUMMY_APPNAME)
DUMMY_REPO = f'tests/{DUMMY_APPNAME}'
DUMMY_VALUES_PATH = join(CHART_DIR_NAME, 'values.yaml')
with change_dir(DUMMY_REPO):
    DUMMY_IMAGE_TAG = lain_meta()

TEST_CLUSTER = 'test'


def run(*args, returncode=0, obj=None, mix_stderr=True, **kwargs):
    """run cli command in a click context"""
    runner = CliRunner(mix_stderr=mix_stderr)
    env = environ.copy()
    obj = obj or {}
    res = runner.invoke(*args, obj=obj, env=env, **kwargs)
    if returncode is not None:
        real_code = rc(res)
        if real_code != returncode:
            print(res.output)
            traceback.print_exception(*res.exc_info)

        assert real_code == returncode

    return res


run(lain, args=['use', TEST_CLUSTER])

with click.Context(click.Command('lain'), obj={}):
    TEST_CLUSTER_CONFIG = tell_cluster_config(TEST_CLUSTER)

DUMMY_URL = f'http://{DUMMY_APPNAME}.{TEST_CLUSTER_CONFIG["domain"]}'
DUMMY_URL_HTTPS = f'https://{DUMMY_APPNAME}.{TEST_CLUSTER_CONFIG["domain"]}'
# this url will point to proc.web-dev in example_lain_yaml
DUMMY_DEV_URL = f'http://{DUMMY_APPNAME}-dev.{TEST_CLUSTER_CONFIG["domain"]}'
RANDOM_STRING = ''.join([choice(ascii_letters) for n in range(9)])
BUILD_TREASURE_NAME = 'treasure.txt'
DUMMY_JOBS_CLAUSE = {
    'init': {
        'initContainers': [
            {
                'name': f'{DUMMY_APPNAME}-init-container',
                'command': ['echo', RANDOM_STRING],
            }
        ],
        'imagePullPolicy': 'Always',
        'command': ['bash', '-c', 'echo nothing >> README.md'],
    },
}
DUMMY_TESTS_CLAUSE = {
    'simple-test': {
        'image': f'{TEST_CLUSTER_CONFIG["registry"]}/lain:latest',
        'command': [
            'bash',
            '-ec',
            '''
            lain -v wait dummy
            ''',
        ],
    },
}


def render_k8s_specs():
    res = run(lain, args=['-s', 'template'], mix_stderr=False)
    return list(yalo(res.stdout, many=True))


def load_dummy_values():
    with open(DUMMY_VALUES_PATH) as f:
        values = yalo(f)

    return values


def tell_ing_name(host, appname, domain, proc):
    host_flat = host.replace('.', '-')
    domain_flat = domain.replace('.', '-')
    if '.' in host:
        return f'{host_flat}-{appname}-{proc}'
    return f'{host_flat}-{domain_flat}-{appname}-{proc}'


def tell_deployed_images(appname):
    res = kubectl(
        'get',
        'deploy',
        '-ojsonpath={..image}',
        '-l',
        f'app.kubernetes.io/name={appname}',
        capture_output=True,
    )
    if rc(res):
        error(res.stdout, exit=1)

    images = set(res.stdout.decode('utf-8').split())
    return images


def run_under_click_context(
    f, args=(), returncode=0, obj=None, kwargs=None
) -> Tuple[click.testing.Result, Any]:
    """to test functions that use click context internally, we must invoke them
    under a active click context, and the only way to do that currently is to
    wrap the function call in a click command"""
    cache = {'func_result': None}
    obj = obj or {}

    @lain.command()
    @click.pass_context
    def wrapper_command(ctx):
        try:
            ensure_helm_initiated()
        except OSError:
            pass
        func_result = f(*args, **(kwargs or {}))
        cache['func_result'] = func_result

    runner = CliRunner()

    res = runner.invoke(lain, args=['wrapper-command'], obj=obj, env=environ)
    if returncode is not None:
        # when things go wrong but shouldn't, print outupt and traceback
        real_code = rc(res)
        if real_code != returncode:
            print(res.output)
            traceback.print_exception(*res.exc_info)

        assert real_code == returncode

    return res, cache['func_result']


@pytest.fixture()
def dummy_rich_ignore(request):
    if not getcwd().endswith(DUMMY_REPO):
        sys.path.append(TESTS_BASE_DIR)
        chdir(DUMMY_REPO)

    ignore_file = join(TESTS_BASE_DIR, DUMMY_APPNAME, GITIGNORE_NAME)
    with open(ignore_file) as f:
        original = f.read()

    def tear_down():
        with open(ignore_file, 'w') as f:
            f.write(original)

        docker_ignore_file = join(TESTS_BASE_DIR, DUMMY_APPNAME, DOCKERIGNORE_NAME)
        ensure_absent(docker_ignore_file)

    extra_ignores = [
        '# comment',
        '!/f1',
        '!f2',
        '/f3',
        'f4',
    ]
    with open(ignore_file, 'a') as f:
        f.write('\n')
        for ig in extra_ignores:
            f.write(ig)
            f.write('\n')

    request.addfinalizer(tear_down)


@pytest.fixture()
def dummy_helm_chart(request):
    def tear_down():
        ensure_absent(
            [CHART_DIR_NAME, join(TESTS_BASE_DIR, DUMMY_APPNAME, DOCKERFILE_NAME)]
        )

    if not getcwd().endswith(DUMMY_REPO):
        sys.path.append(TESTS_BASE_DIR)
        chdir(DUMMY_REPO)

    tear_down()
    run(lain, args=['init', '-f'])
    request.addfinalizer(tear_down)


@pytest.fixture()
def dummy(request):
    def tear_down():
        # 拆除测试的结果就不要要求这么高了, 因为有时候会打断点手动调试
        # 跑这段拆除代码的时候, 可能东西已经被拆干净了
        run(lain, args=['delete', '--purge'], returncode=None)
        helm('delete', DUMMY_OVERRIDE_RELEASE_NAME, check=False)
        ensure_absent(
            [CHART_DIR_NAME, join(TESTS_BASE_DIR, DUMMY_REPO, DOCKERFILE_NAME)]
        )

    if not getcwd().endswith(DUMMY_REPO):
        sys.path.append(TESTS_BASE_DIR)
        chdir(DUMMY_REPO)

    tear_down()
    run(lain, args=['init'])
    override_values_for_e2e = {
        'deployments': {'web': {'terminationGracePeriodSeconds': 1}}
    }
    override_values_file = f'values-{TEST_CLUSTER}.yaml'
    yadu(override_values_for_e2e, join(CHART_DIR_NAME, override_values_file))
    # `lain secret show` will create a dummy secret
    run(lain, args=['secret', 'show'])
    request.addfinalizer(tear_down)


@pytest.fixture()
def registry(request):
    cc = dict(CLUSTERS[TEST_CLUSTER])
    return tell_registry_client(cc)


def dic_contains(big, small):
    left = big.copy()
    left.update(small)
    assert left == big
