from copy import deepcopy
from os.path import join
from time import sleep

import pytest
import requests
from tenacity import retry, stop_after_attempt, wait_fixed

from lain_cli.lain import lain
from lain_cli.utils import (
    DEFAULT_WORKDIR,
    KUBECONFIG_DIR,
    context,
    docker,
    ensure_absent,
    ensure_str,
    get_pods,
    helm_status,
    jalo,
    kubectl,
    lain_build,
    lain_image,
    lain_meta,
    make_job_name,
    pick_pod,
    tell_pod_deploy_name,
    yadu,
)
from tests.conftest import (
    BUILD_TREASURE_NAME,
    CHART_DIR_NAME,
    DUMMY_APPNAME,
    DUMMY_CANARY_NAME,
    DUMMY_DEV_URL,
    DUMMY_IMAGE_TAG,
    DUMMY_JOBS_CLAUSE,
    DUMMY_OVERRIDE_RELEASE_NAME,
    DUMMY_TESTS_CLAUSE,
    DUMMY_URL,
    DUMMY_VALUES_PATH,
    RANDOM_STRING,
    TEST_CLUSTER,
    TEST_CLUSTER_CONFIG,
    load_dummy_values,
    run,
    run_under_click_context,
    tell_deployed_images,
    tell_ing_name,
)


@pytest.mark.first
@pytest.mark.usefixtures('dummy_helm_chart')
def test_build(registry):
    stage = 'prepare'

    def _prepare():
        obj = context().obj
        values = obj['values']
        build_clause = values['build']
        build_clause['prepare']['env'] = {
            'prepare_env': BUILD_TREASURE_NAME,
            'escape_test': 'space test & newline \n test',
        }
        build_clause['prepare']['keep'].extend(
            [
                'foo/thing.txt',
                'bar',
            ]
        )
        build_clause['prepare']['script'].extend(
            [
                f'echo {RANDOM_STRING} > {BUILD_TREASURE_NAME}',
                'mkdir foo bar',
                'touch foo/thing.txt bar/thing.txt',
            ]
        )
        lain_build(stage=stage)

    run_under_click_context(_prepare)
    _, prepare_image = run_under_click_context(lain_image, kwargs={'stage': stage})
    res = docker_run(prepare_image, ['ls'])
    ls_result = parse_ls(res.stdout)
    # ensure keep clause works as expected
    assert ls_result == {'foo', 'bar', 'chart', BUILD_TREASURE_NAME}
    res = docker_run(prepare_image, ['env'])
    envs = ensure_str(res.stdout).splitlines()
    assert f'prepare_env={BUILD_TREASURE_NAME}' in envs
    assert 'escape_test=space test & newline \\n test' in envs

    stage = 'build'

    def _build_without_prepare():
        obj = context().obj
        values = obj['values']
        build_clause = values['build']
        build_clause['env'] = {'build_env': BUILD_TREASURE_NAME}
        del build_clause['prepare']
        lain_build(stage=stage, push=False)

    run_under_click_context(_build_without_prepare)
    _, build_image = run_under_click_context(lain_image, kwargs={'stage': stage})
    # 这次 build 是虚假的, 没有经过 prepare 步骤, 所以肯定不会有 treasure.txt
    res = docker_run(build_image, ['ls'])
    ls_result = parse_ls(res.stdout)
    assert 'run.py' in ls_result
    assert BUILD_TREASURE_NAME not in ls_result
    res = docker_run(build_image, ['env'])
    assert f'build_env={BUILD_TREASURE_NAME}' in ensure_str(res.stdout)

    def _build():
        obj = context().obj
        values = obj['values']
        build_clause = values['build']
        build_clause['script'].append(f'echo {RANDOM_STRING} >> {BUILD_TREASURE_NAME}')
        lain_build(stage=stage)

    run_under_click_context(_build)
    _, build_image = run_under_click_context(lain_image, kwargs={'stage': stage})
    res = docker_run(build_image, ['env'])
    env_lines = ensure_str(res.stdout).splitlines()
    _, meta = run_under_click_context(lain_meta)
    assert f'LAIN_META={meta}' in env_lines
    res = docker_run(build_image, ['cat', BUILD_TREASURE_NAME])
    treasure = ensure_str(res.stdout).strip()
    # 这个文件被我打印了两次随机串进去, 因此应该就两行...无聊的测试
    assert treasure == f'{RANDOM_STRING}\n{RANDOM_STRING}'
    res = docker_run(build_image, ['ls'])
    ls_result = parse_ls(res.stdout)
    assert 'run.py' in ls_result
    run(lain, args=['push'])
    recent_tags = registry.list_tags(DUMMY_APPNAME)
    latest_tag = max(t for t in recent_tags if t != 'latest')
    assert build_image.rsplit(':', 1)[-1] == latest_tag

    stage = 'release'

    def _release():
        obj = context().obj
        values = obj['values']
        values['release'] = {
            'env': {'release_env': BUILD_TREASURE_NAME},
            'dest_base': 'python:latest',
            'workdir': DEFAULT_WORKDIR,
            'script': [],
            'copy': [
                {'src': '/lain/app/treasure.txt', 'dest': '/lain/app/treasure.txt'},
                {'src': '/lain/app/treasure.txt', 'dest': '/etc'},
            ],
        }
        lain_build(stage=stage, push=False)

    run_under_click_context(_release)
    _, release_image = run_under_click_context(lain_image, kwargs={'stage': stage})
    res = docker_run(release_image, ['ls'])
    ls_result = parse_ls(res.stdout)
    assert ls_result == {BUILD_TREASURE_NAME}
    res = docker_run(release_image, ['ls', '-alh', f'/etc/{BUILD_TREASURE_NAME}'])
    ls_result = ensure_str(res.stdout).strip()
    # check file permission
    assert '1001 1001' in ls_result
    assert ls_result.endswith(f'/etc/{BUILD_TREASURE_NAME}')
    res = docker_run(release_image, ['cat', BUILD_TREASURE_NAME])
    treasure = ensure_str(res.stdout).strip()
    # 构建 release 镜像的时候, 由于并没有超载 build.script, 因此 treasure
    # 里只有一行
    assert treasure == f'{RANDOM_STRING}'
    res = docker_run(release_image, ['env'])
    assert f'release_env={BUILD_TREASURE_NAME}' in ensure_str(res.stdout)


@pytest.mark.second
@pytest.mark.usefixtures('dummy')
def test_workflow(registry):
    # lain init should failed when chart directory already exists
    run(lain, args=['init'], returncode=1)
    # use -f to remove chart directory and redo
    run(lain, args=['init', '-f'])
    # lain use will switch current context switch to [TEST_CLUSTER]
    run(lain, args=['use', TEST_CLUSTER])
    # lain use will print current cluster
    res = run(lain, args=['use'])
    assert f'* {TEST_CLUSTER}' in ensure_str(res.stdout)
    # this makes sure lain-use can work when kubeconfig is absent
    ensure_absent(join(KUBECONFIG_DIR, 'config'))
    run(lain, args=['use', TEST_CLUSTER])
    # see if this image is actually present on registry
    res = run(lain, args=['image'])
    image_tag = res.stdout.strip().split(':')[-1]
    # should fail when using a bad image tag
    res = run(lain, args=['deploy', '--set', 'imageTag=noway'], returncode=1)
    assert 'image not found' in ensure_str(res.output).lower()
    cronjob_name = 'nothing'
    override_values = {
        # 随便加一个 job, 为了看下一次部署的时候能否顺利先清理掉这个 job
        'jobs': DUMMY_JOBS_CLAUSE,
        # 随便加一个 cronjob, 为了测试 lain create-job
        'cronjobs': {
            cronjob_name: {
                'schedule': '0 0 * * *',
                'command': ['echo', RANDOM_STRING],
            },
        },
    }
    yadu(override_values, f'{CHART_DIR_NAME}/values-{TEST_CLUSTER}.yaml')
    # use a built image to deploy
    run(lain, args=['--ignore-lint', 'deploy', '--set', f'imageTag={image_tag}'])
    res = run(lain, args=['create-job', cronjob_name])
    create_job_cmd = f'kubectl create job --from=cronjob/{DUMMY_APPNAME}-{cronjob_name} manual-test-{cronjob_name}'
    assert create_job_cmd in res.output
    # check service is up
    dummy_resp = url_get_json(DUMMY_URL)
    assert dummy_resp['env']['FOO'] == 'BAR'
    assert dummy_resp['secretfile'] == 'I\nAM\nBATMAN'
    # check if hostAliases is working
    assert 'localhost' in dummy_resp['hosts']
    assert 'local' in dummy_resp['hosts']
    # check imageTag is correct
    deployed_images = tell_deployed_images(DUMMY_APPNAME)
    assert len(deployed_images) == 1
    deployed_image = deployed_images.pop()
    assert deployed_image.endswith(image_tag)

    # check if init job succeeded
    wait_for_job_success()
    # run a extra job, to test lain job functionalities
    command = 'env'
    res = run(lain, args=['job', '--force', command])
    _, job_name = run_under_click_context(make_job_name, args=(command,))
    pod_name = wait_for_job_success(job_name)
    _, pod_name_again = run_under_click_context(
        pick_pod, kwargs={'selector': f'job-name={job_name}'}
    )
    # check if pick_pod works correctly
    assert pod_name == pod_name_again
    logs_res = kubectl('logs', pod_name, capture_output=True)
    logs = ensure_str(logs_res.stdout)
    assert 'FOO=BAR' in logs
    # 跑第二次只是为了看看清理过程能否顺利执行, 保证不会报错
    run(lain, args=['job', '--force', 'env'])

    values = load_dummy_values()
    web_proc = values['deployments']['web']
    web_proc.update(
        {
            'imagePullPolicy': 'Always',
            'terminationGracePeriodSeconds': 1,
        }
    )
    # add one extra ingress rule to values.yaml
    dev_host = f'{DUMMY_APPNAME}-dev'
    full_host = 'dummy.full.domain'
    values['ingresses'].extend(
        [
            {'host': dev_host, 'deployName': 'web-dev', 'paths': ['/']},
            {'host': full_host, 'deployName': 'web', 'paths': ['/']},
        ]
    )
    values['jobs'] = {'init': {'command': ['echo', 'migrate']}}
    yadu(values, DUMMY_VALUES_PATH)
    overrideReplicaCount = 3
    overrideImageTag = 'latest'
    # add another env
    run(lain, args=['env', 'add', 'SCALE=BANANA'])
    web_dev_proc = deepcopy(web_proc)
    web_dev_proc.update(
        {
            'replicaCount': overrideReplicaCount,
            'imageTag': overrideImageTag,
        }
    )
    # adjust replicaCount and imageTag in override values file
    override_values = {
        'deployments': {
            'web-dev': web_dev_proc,
        },
        # this is just used to ensure helm template rendering
        'ingressAnnotations': {
            'nginx.ingress.kubernetes.io/proxy-next-upstream-timeout': 1,
        },
        'externalIngresses': [
            {'host': 'dummy-public.foo.cn', 'deployName': 'web', 'paths': ['/']},
            {'host': 'dummy-public.bar.cn', 'deployName': 'web', 'paths': ['/']},
        ],
    }
    yadu(override_values, f'{CHART_DIR_NAME}/values-{TEST_CLUSTER}.yaml')

    def get_helm_values():
        ctx = context()
        helm_values = ctx.obj['values']
        return helm_values

    # check if values-[TEST_CLUSTER].yaml currectly overrides helm context
    _, helm_values = run_under_click_context(get_helm_values)
    assert helm_values['deployments']['web-dev']['replicaCount'] == overrideReplicaCount

    # deploy again to create newly added ingress rule
    run(lain, args=['deploy', '--set', f'imageTag={DUMMY_IMAGE_TAG}'])
    # check if the new ingress rule is created
    res = kubectl(
        'get',
        'ing',
        '-l',
        f'app.kubernetes.io/name={DUMMY_APPNAME}',
        '-o=jsonpath={..metadata.name}',
        capture_output=True,
    )
    assert not res.returncode
    domain = TEST_CLUSTER_CONFIG['domain']
    assert set(res.stdout.decode('utf-8').split()) == {
        tell_ing_name(full_host, DUMMY_APPNAME, domain, 'web'),
        tell_ing_name(DUMMY_APPNAME, DUMMY_APPNAME, domain, 'web'),
        f'dummy-public-foo-cn-{DUMMY_APPNAME}-web',
        tell_ing_name(dev_host, DUMMY_APPNAME, domain, 'web-dev'),
        f'dummy-public-bar-cn-{DUMMY_APPNAME}-web',
    }
    # check pod name match its corresponding deploy name
    dummy_resp = url_get_json(DUMMY_URL)
    assert tell_pod_deploy_name(dummy_resp['env']['HOSTNAME']) == f'{DUMMY_APPNAME}-web'
    dummy_dev_resp = url_get_json(DUMMY_DEV_URL)
    assert (
        tell_pod_deploy_name(dummy_dev_resp['env']['HOSTNAME'])
        == f'{DUMMY_APPNAME}-web-dev'
    )
    # env is overriden in dummy-dev, see default values.yaml
    assert dummy_dev_resp['env']['FOO'] == 'BAR'
    assert dummy_dev_resp['env']['SCALE'] == 'BANANA'
    assert dummy_dev_resp['env']['LAIN_CLUSTER'] == TEST_CLUSTER
    assert dummy_dev_resp['env']['K8S_NAMESPACE'] == TEST_CLUSTER_CONFIG.get(
        'namespace', 'default'
    )
    assert dummy_dev_resp['env']['IMAGE_TAG'] == DUMMY_IMAGE_TAG
    # check if replicaCount is correctly overriden
    res = kubectl(
        'get',
        'deploy',
        f'{DUMMY_APPNAME}-web-dev',
        '-o=jsonpath={.spec.replicas}',
        capture_output=True,
    )
    assert res.stdout.decode('utf-8').strip() == str(overrideReplicaCount)
    # check if imageTag is correctly overriden
    web_image = get_deploy_image(f'{DUMMY_APPNAME}-web')
    assert web_image.endswith(DUMMY_IMAGE_TAG)
    web_dev_image = get_deploy_image(f'{DUMMY_APPNAME}-web-dev')
    assert web_dev_image.endswith(overrideImageTag)
    # rollback imageTag for web-dev using `lain update_image`
    run(lain, args=['update-image', 'web-dev'])
    # restart a few times to test lain restart functionalities
    run(lain, args=['restart', 'web', '--wait'])
    run(lain, args=['restart', '--graceful', '--wait'])
    dummy_dev_resp = url_get_json(DUMMY_DEV_URL)
    # if dummy-dev is at the correct imageTag, that means lain update-image is
    # working correctly, and lain restart too
    assert dummy_dev_resp['env']['IMAGE_TAG'] == DUMMY_IMAGE_TAG
    run(lain, args=['--auto-pilot', 'env', 'add', f'treasure={RANDOM_STRING}'])
    dummy_resp = url_get_json(DUMMY_URL)
    # --auto-pilot will trigger a graceful restart, verify by confirming the
    # added env inside the freshly created containers
    assert dummy_resp['env']['treasure'] == RANDOM_STRING


@pytest.mark.run(after='test_workflow')
@pytest.mark.usefixtures('dummy')
def test_canary():
    res = run(lain, args=['deploy', '--canary'], returncode=1)
    assert 'cannot initiate canary deploy' in ensure_str(res.output)
    run(lain, args=['deploy'])
    res = run(lain, args=['deploy', '--canary'])
    assert 'canary version has been deployed' in ensure_str(res.output)
    res = run(lain, args=['deploy'], returncode=1)
    assert 'cannot proceed due to on-going canary deploy' in ensure_str(res.output)
    resp = url_get_json(DUMMY_URL)
    assert resp['env']['HOSTNAME'].startswith(f'{DUMMY_APPNAME}-web')
    res = run(lain, args=['set-canary-group', 'internal'], returncode=1)
    assert 'canaryGroups not defined in values' in ensure_str(res.output)
    # inject canary annotations for test purpose
    values = load_dummy_values()
    canary_header_name = 'canary'
    values['canaryGroups'] = {
        'internal': {
            'nginx.ingress.kubernetes.io/canary-by-header': canary_header_name
        },
    }
    yadu(values, DUMMY_VALUES_PATH)
    run(lain, args=['set-canary-group', 'internal'])
    ings_res = kubectl(
        'get',
        'ing',
        '-ojson',
        '-l',
        f'helm.sh/chart={DUMMY_CANARY_NAME}',
        capture_output=True,
    )
    ings = jalo(ings_res.stdout)
    for ing in ings['items']:
        annotations = ing['metadata']['annotations']
        assert (
            annotations['nginx.ingress.kubernetes.io/canary-by-header']
            == canary_header_name
        )

    canary_header = {canary_header_name: 'always'}
    resp = url_get_json(DUMMY_URL, headers=canary_header)
    assert resp['env']['HOSTNAME'].startswith(f'{DUMMY_CANARY_NAME}-web')
    run(lain, args=['set-canary-group', '--abort'])
    run(lain, args=['wait'])
    assert f'{DUMMY_CANARY_NAME}-web' not in get_dummy_pod_names()
    values['tests'] = DUMMY_TESTS_CLAUSE
    yadu(values, DUMMY_VALUES_PATH)
    tag = 'latest'
    run(lain, args=['deploy', '--set', f'imageTag={tag}', '--canary'])
    run(lain, args=['set-canary-group', '--final'])
    run(lain, args=['wait'])
    assert f'{DUMMY_CANARY_NAME}-web' not in get_dummy_pod_names()
    image = get_deploy_image(f'{DUMMY_APPNAME}-web')
    assert image.endswith(f':{tag}')


@pytest.mark.run(after='test_canary')
@pytest.mark.usefixtures('dummy')
def test_override_release_name():
    override_values_file_path = join(CHART_DIR_NAME, 'values-override.yaml')
    override_values = {
        'releaseName': DUMMY_OVERRIDE_RELEASE_NAME,
        'ingresses': [
            {
                'host': DUMMY_OVERRIDE_RELEASE_NAME,
                'deployName': 'web',
                'paths': ['/'],
            }
        ],
    }
    yadu(override_values, override_values_file_path)
    override_args = ['-f', override_values_file_path]
    run(lain, args=override_args + ['deploy'])
    status_dic = helm_status(DUMMY_OVERRIDE_RELEASE_NAME)
    # helm release name should be correctly overridden
    assert status_dic['name'] == DUMMY_OVERRIDE_RELEASE_NAME
    # deploy a 'normal' version, to assure two releases do not interfere
    run(lain, args=['deploy', '--wait'])
    # get pods by appname, rather than releaseName
    _, pods = get_pods(appname=DUMMY_APPNAME)
    deploys = set()
    for pod in pods:
        pod_name, *_ = pod.split(None, 1)
        if pod_name.endswith('test'):
            # ignore test container
            continue
        deploy_name = tell_pod_deploy_name(pod_name)
        if deploy_name == 'dummy':
            # this is job pod, not deploy
            continue
        deploys.add(deploy_name)

    assert deploys == {f'{DUMMY_APPNAME}-web', f'{DUMMY_OVERRIDE_RELEASE_NAME}-web'}
    assert f'{DUMMY_OVERRIDE_RELEASE_NAME}-web' in ''.join(pods)
    assert f'{DUMMY_APPNAME}-web' in ''.join(pods)
    res = run(lain, args=override_args + ['deploy', '--canary'], returncode=1)
    assert 'do not use canary deploy while values are being overridden' in res.stdout
    run(lain, args=override_args + ['delete'])
    # overridden release is deleted, but the 'normal' app remains intact
    assert not helm_status(DUMMY_OVERRIDE_RELEASE_NAME)
    assert helm_status(DUMMY_APPNAME)['name'] == DUMMY_APPNAME


@pytest.mark.run(after='test_override_release_name')
@pytest.mark.usefixtures('dummy')
def test_sts():
    # sts values are mostly the same with deploy, we just have to change a few
    # things to make it work
    values = load_dummy_values()
    sts = deepcopy(values['deployments']['web'])
    override_values = {
        'statefulSets': {
            'worker': sts,
        }
    }
    yadu(override_values, f'{CHART_DIR_NAME}/values-{TEST_CLUSTER}.yaml')
    run(lain, args=['deploy'])
    _, pod_name = run_under_click_context(pick_pod, kwargs={'proc_name': 'worker'})
    assert pod_name == f'{DUMMY_APPNAME}-worker-0'


@pytest.mark.run(after='test_override_release_name')
@pytest.mark.usefixtures('dummy')
def test_lain_job_in_non_lain_app_directory():
    ensure_absent([CHART_DIR_NAME])
    command = ('which', 'lain')
    run(lain, args=['job', '--wait', '--force', *command])
    _, job_name = run_under_click_context(
        make_job_name, args=(command,), obj={'appname': 'lain'}
    )
    logs_res = kubectl('logs', f'-ljob-name={job_name}', capture_output=True)
    assert ensure_str(logs_res.stdout).strip() == '/usr/local/bin/lain'


@retry(reraise=True, wait=wait_fixed(3), stop=stop_after_attempt(6))
def url_get_json(url, **kwargs):
    sleep(4)
    res = requests.get(url, **kwargs)
    res.raise_for_status()
    return res.json()


def get_dummy_pod_names():
    res = kubectl(
        'get',
        'po',
        f'-lapp.kubernetes.io/name={DUMMY_APPNAME}',
        capture_output=True,
    )
    pods = ensure_str(res.stdout).splitlines()
    names = []
    for podline in pods:
        pod_name, _, status, *_ = podline.split()
        # ignore dying pods
        if status == 'Terminating':
            continue
        names.append(pod_name)

    return ' '.join(names)


def get_deploy_image(deploy_name):
    res = kubectl(
        'get',
        'deploy',
        deploy_name,
        '-o=jsonpath={.spec.template.spec..image}',
        capture_output=True,
    )
    return res.stdout.decode('utf-8').strip()


@retry(reraise=True, wait=wait_fixed(1), stop=stop_after_attempt(6))
def wait_for_job_success(job_name=None):
    if not job_name:
        job_name = f'{DUMMY_APPNAME}-init'

    sleep(2)
    res = kubectl(
        'get',
        'po',
        '-o=jsonpath={range .items[*]}{@.metadata.name}{" "}{@.status.phase}{end}',
        '-l',
        f'job-name={job_name}',
        capture_output=True,
    )
    stdout = ensure_str(res.stdout).strip()
    assert stdout.endswith('Succeeded')
    return stdout.split(None, 1)[0]


def docker_run(image, cmd, name=None):
    name_clause = ('--name', name) if name else []
    return docker('run', '--rm', *name_clause, image, *cmd, capture_output=True)


def parse_ls(s):
    return set(ensure_str(s).strip().split())
