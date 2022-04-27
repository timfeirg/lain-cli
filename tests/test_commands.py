from os.path import isfile, join

import pytest

from lain_cli.lain import lain
from lain_cli.utils import CLI_DIR, docker_save_name, ensure_absent, lain_meta, yalo
from tests.conftest import (
    CHART_DIR_NAME,
    DUMMY_APPNAME,
    DUMMY_IMAGE_TAG,
    DUMMY_VALUES_PATH,
    TEST_CLUSTER,
    run,
    run_under_click_context,
)


@pytest.mark.usefixtures('dummy_helm_chart')
def test_lain_init_with_values_j2():
    values_j2 = f'{CHART_DIR_NAME}/values.yaml.j2'
    j2 = 'appname: {{ appname }}'
    with open(values_j2, 'w') as f:
        f.write(j2)

    res = run(lain, args=['init'], returncode=1)
    assert 'already exists' in res.output
    run(lain, args=['--ignore-lint', 'init', '-f'])
    values = yalo(DUMMY_VALUES_PATH)
    assert values == {'appname': DUMMY_APPNAME}


@pytest.mark.last  # this test cannot run in parallel with other e2e tests
@pytest.mark.usefixtures('dummy')
def test_secret_env_edit():
    run(lain, args=['env', 'edit'])
    res = run(lain, args=['env', 'show'])
    modified_env = yalo(res.output)
    # the original data will be preserved
    assert 'FOO' in modified_env['data']
    # our fake $EDITOR will write a key called SURPRISE
    assert 'SURPRISE' in modified_env['data']
    res = run(lain, args=['secret', 'edit'])
    res = run(lain, args=['secret', 'show'])
    modified_secret = yalo(res.output)
    assert 'topsecret.txt' in modified_secret['data']
    assert 'SURPRISE' in modified_secret['data']


@pytest.mark.last
@pytest.mark.usefixtures('dummy')
def test_lain_save():
    res = run(lain, args=['save', '--force', '--retag', TEST_CLUSTER])
    fname = f'{DUMMY_APPNAME}_{DUMMY_IMAGE_TAG}.tar.gz'
    assert res.output.strip().endswith(fname)
    retag = f'{DUMMY_APPNAME}-again'
    run(lain, args=['save', '--retag', retag])
    _, meta = run_under_click_context(lain_meta)
    fname = docker_save_name(f'{retag}:{meta}')
    # file is generated in lain-cli repo root, not dummy dir, sorry
    exists_and_delete(join(CLI_DIR, '..', fname))
    retag = f'{DUMMY_APPNAME}-again:latest'
    run(lain, args=['save', '--retag', retag])
    fname = docker_save_name(retag)
    exists_and_delete(join(CLI_DIR, '..', fname))


def exists_and_delete(path):
    assert isfile(path)
    ensure_absent(path)
