import shutil
from os.path import basename, exists, join
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

import pytest
from ruamel.yaml.scalarstring import LiteralScalarString

from lain_cli.aliyun import AliyunRegistry
from lain_cli.harbor import HarborRegistry
from lain_cli.utils import (
    CLUSTER_VALUES_DIR,
    DOCKERIGNORE_NAME,
    banyun,
    change_dir,
    context,
    ensure_absent,
    ensure_str,
    find,
    lain_meta,
    load_helm_values,
    make_docker_ignore,
    make_job_name,
    subprocess_run,
    tell_all_clusters,
    tell_cluster,
    tell_cluster_config,
    tell_git_ignore,
    tell_helm_options,
    tell_ingress_urls,
    tell_job_names,
    tell_release_name,
    yadu,
    yalo,
)
from tests.conftest import (
    CHART_DIR_NAME,
    DUMMY_APPNAME,
    DUMMY_JOBS_CLAUSE,
    DUMMY_OVERRIDE_RELEASE_NAME,
    DUMMY_REPO,
    DUMMY_TESTS_CLAUSE,
    DUMMY_URL,
    DUMMY_URL_HTTPS,
    RANDOM_STRING,
    TEST_CLUSTER,
    run_under_click_context,
)

BULLSHIT = '不过我倒不在乎做什么工作,只要没人认识我,我也不认识他们就行了。我还会装作自己是个又聋又哑的人。这样我就可以不必跟任何人讲些他妈的没意思的废话。'


@pytest.mark.usefixtures('dummy_helm_chart')
def test_make_job_name():
    _, res = run_under_click_context(make_job_name, args=[''])
    assert res == 'dummy-5562bd9d33e0c6ce'  # this is a stable hash value


@pytest.mark.usefixtures('dummy_helm_chart')
def test_ensure_absent():
    values_j2 = f'{CHART_DIR_NAME}/values.yaml.j2'
    Path(values_j2).touch()
    ensure_absent(CHART_DIR_NAME, preserve=[values_j2, f'{CHART_DIR_NAME}/not-here'])
    left_over = find(CHART_DIR_NAME)
    assert list(left_over) == [basename(values_j2)]
    ensure_absent(CHART_DIR_NAME)
    assert not exists(CHART_DIR_NAME)


def test_ya():
    dic = {'slogan': BULLSHIT}
    f = NamedTemporaryFile()
    yadu(dic, f)
    f.seek(0)
    assert yalo(f) == dic
    multiline_content = {'so': LiteralScalarString('so\nlong')}
    s = yadu(multiline_content)
    # should dump multiline string in readable format
    assert ': |' in s


@pytest.mark.usefixtures('dummy_helm_chart')
def test_subprocess_run():
    cmd = ['helm', 'version', '--bad-flag']
    cmd_result, func_result = run_under_click_context(
        subprocess_run,
        args=[cmd],
        kwargs={'check': True},
        returncode=1,
    )
    # sensible output in stderr, rather than python traceback
    assert 'unknown flag: --bad-flag' in cmd_result.output

    cmd_result, func_result = run_under_click_context(
        subprocess_run,
        args=[cmd],
        kwargs={'abort_on_fail': True},
        returncode=1,
    )
    # abort_on_fail will not capture std
    assert 'unknown flag: --bad-flag' not in cmd_result.output

    cmd = ['helm', 'version']
    cmd_result, func_result = run_under_click_context(
        subprocess_run,
        args=[cmd],
        kwargs={'check': True, 'capture_output': True},
    )
    assert 'version' in ensure_str(func_result.stdout)

    cmd = 'pwd | cat'
    _, func_result = run_under_click_context(
        subprocess_run,
        args=[cmd],
        kwargs={'shell': True, 'capture_output': True, 'check': True},
    )
    wd = ensure_str(func_result.stdout).strip()
    assert wd.endswith(DUMMY_REPO)


@pytest.mark.usefixtures('dummy_helm_chart')
def test_tell_cluster():
    _, func_result = run_under_click_context(tell_cluster)
    assert func_result == TEST_CLUSTER


def test_lain_meta():
    not_a_git_dir = TemporaryDirectory()
    with change_dir(not_a_git_dir.name):
        assert lain_meta() == 'latest'


@pytest.mark.usefixtures('dummy_helm_chart')
def test_banyun():
    cli_result, _ = run_under_click_context(banyun, ('not-a-image',), returncode=1)
    assert 'not a valid image tag' in cli_result.stdout


@pytest.mark.usefixtures('dummy_helm_chart')
def test_load_helm_values():
    # test internal cluster values are correctly loaded
    _, values = run_under_click_context(
        load_helm_values,
    )
    assert values['registry'] == 'docker.io/timfeirg'
    assert values['domain'] == 'info'
    dummy_jobs = {
        'init': {'command': ['echo', 'nothing']},
    }
    override_values = {
        'jobs': dummy_jobs,
    }
    yadu(override_values, f'{CHART_DIR_NAME}/values-{TEST_CLUSTER}.yaml')
    _, values = run_under_click_context(
        load_helm_values,
    )
    assert values['jobs'] == dummy_jobs


@pytest.mark.usefixtures('dummy_helm_chart')
def test_tell_helm_options():
    _, options = run_under_click_context(
        tell_helm_options,
    )
    internal_values_file = join(CLUSTER_VALUES_DIR, f'values-{TEST_CLUSTER}.yaml')
    assert internal_values_file in set(options)
    set_values = parse_helm_set_clause_from_options(options)
    assert set_values['cluster'] == 'test'
    assert set_values.get('imageTag')

    def no_build_and_override_registry():
        obj = context().obj
        values = obj['values']
        del values['build']
        pairs = [('registry', RANDOM_STRING)]
        return tell_helm_options(pairs)

    _, options = run_under_click_context(
        no_build_and_override_registry,
    )
    set_values_again = parse_helm_set_clause_from_options(options)
    assert 'imageTag' not in set_values_again
    del set_values['imageTag']
    assert set_values_again.pop('registry', None) == RANDOM_STRING
    assert set_values_again == set_values

    def with_extra_values_file():
        obj = context().obj
        dic = {'labels': {'foo': 'bar'}}
        f = NamedTemporaryFile(prefix='values-extra', suffix='.yaml')
        yadu(dic, f)
        f.seek(0)
        obj['extra_values_file'] = f
        try:
            return tell_helm_options()
        finally:
            del f

    _, options = run_under_click_context(
        with_extra_values_file,
    )
    extra_values_file_name = basename(options.pop(-1))
    assert extra_values_file_name.startswith('values-extra')
    assert extra_values_file_name.endswith('.yaml')


def parse_helm_set_clause_from_options(options):
    set_clause = options[options.index('--set') + 1]
    pair_list = set_clause.split(',')
    res = {}
    for pair in pair_list:
        print(pair)
        k, v = pair.split('=')
        res[k] = v

    return res


@pytest.mark.usefixtures('dummy_helm_chart')
def test_registry():
    region_id = 'cn-hangzhou'
    repo_ns = 'big-company'
    registry = f'registry.{region_id}.aliyuncs.com/{repo_ns}'
    aliyun_registry = AliyunRegistry(
        access_key_id='hh',
        access_key_secret='hh',
        registry=registry,
    )
    tag = 'noway'
    _, image = run_under_click_context(
        aliyun_registry.make_image,
        args=[tag],
    )
    assert image == f'{registry}/{DUMMY_APPNAME}:{tag}'
    project = 'foo'
    registry_url = f'harbor.fake/{project}'
    harbor_registry = HarborRegistry(registry_url, 'fake-token')
    tag = 'noway'
    _, image = run_under_click_context(
        harbor_registry.make_image,
        args=[tag],
    )
    assert harbor_registry.registry == registry_url
    assert image == f'{registry_url}/{DUMMY_APPNAME}:{tag}'


@pytest.mark.usefixtures('dummy_rich_ignore')
def test_ignore_files():
    _, content = run_under_click_context(
        tell_git_ignore,
    )
    assert content.splitlines()

    _, content = run_under_click_context(
        make_docker_ignore,
    )
    with open(DOCKERIGNORE_NAME) as f:
        docker_ignore = f.read()
        docker_ignores = docker_ignore.splitlines()

    assert 'comment' not in docker_ignore
    assert '**/.git' in docker_ignores
    assert '!f1' in docker_ignores
    assert '!**/f2' in docker_ignores
    assert 'f3' in docker_ignores
    assert '**/f4' in docker_ignores


@pytest.mark.usefixtures('dummy_helm_chart')
def test_tell_job_names():
    override_values = {
        'jobs': DUMMY_JOBS_CLAUSE,
        'tests': DUMMY_TESTS_CLAUSE,
    }
    yadu(override_values, f'{CHART_DIR_NAME}/values-{TEST_CLUSTER}.yaml')
    _, content = run_under_click_context(
        tell_job_names,
    )
    assert set(content) == {'dummy-init'}


@pytest.mark.usefixtures('dummy_helm_chart')
def test_tell_release_name():
    _, content = run_under_click_context(
        tell_release_name,
    )
    assert content == DUMMY_APPNAME
    override_values = {'releaseName': DUMMY_OVERRIDE_RELEASE_NAME}
    yadu(override_values, f'{CHART_DIR_NAME}/values-{TEST_CLUSTER}.yaml')
    _, content = run_under_click_context(
        tell_release_name,
    )
    assert content == DUMMY_OVERRIDE_RELEASE_NAME


@pytest.mark.usefixtures('dummy_helm_chart')
def test_cluster_values_override():
    fake_registry = 'registry.example.com'
    override_values = {
        'registry': fake_registry,
    }
    yadu(override_values, f'{CHART_DIR_NAME}/values-{TEST_CLUSTER}.yaml')
    _, cc = run_under_click_context(
        tell_cluster_config,
    )
    assert cc['registry'] == fake_registry


@pytest.mark.usefixtures('dummy_helm_chart')
def test_tell_all_clusters(mocker):
    test_cluster_values_file = f'values-{TEST_CLUSTER}.yaml'
    # we need at least two clusters to verify that tell_all_clusters are working correctly
    another_cluster_name = 'another'
    another_cluster_values_file = f'values-{another_cluster_name}.yaml'
    tempd = TemporaryDirectory()
    test_cluster_values_path = join(CLUSTER_VALUES_DIR, test_cluster_values_file)
    test_cluster_values = yalo(test_cluster_values_path)
    test_cluster_values['registry'] = 'another.example.com'
    shutil.copyfile(
        test_cluster_values_path, join(tempd.name, test_cluster_values_file)
    )
    yadu(test_cluster_values, join(tempd.name, another_cluster_values_file))
    mocker.patch('lain_cli.utils.KUBECONFIG_DIR', tempd.name)
    mocker.patch('lain_cli.utils.CLUSTER_VALUES_DIR', tempd.name)
    # touch kubeconfig-another
    Path(join(tempd.name, f'kubeconfig-{another_cluster_name}')).write_text('')
    Path(join(tempd.name, f'kubeconfig-{TEST_CLUSTER}')).write_text('')
    # now that kubeconfig and cluster values file are present, we can verify
    # CLUSTERS is correct
    _, ccs = run_under_click_context(
        tell_all_clusters,
    )
    assert set(ccs) == {TEST_CLUSTER, another_cluster_name}
    assert ccs['another']['registry'] == test_cluster_values['registry']
    tempd.cleanup()


@pytest.mark.usefixtures('dummy_helm_chart')
def test_tell_ingress_urls():
    _, urls = run_under_click_context(
        tell_ingress_urls,
    )
    assert set(urls) == set([f'{DUMMY_URL_HTTPS}/', f'{DUMMY_URL}/'])
