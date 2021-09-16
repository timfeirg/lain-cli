import pathlib
import re
from os import getcwd as cwd
from os.path import join

import gitlab
from click import BadParameter

from lain_cli.utils import (
    change_dir,
    debug,
    error,
    lain_,
    must_get_env,
    tell_cluster_config,
)

CWD = cwd()
REPO_NAME_GEX = re.compile(r'\w+/\w+')


def get_gitlab():
    cc = tell_cluster_config()
    endpoint = cc.get('gitlab')
    if not endpoint:
        error('gitlab not configured in cluster config', exit=1)

    token = must_get_env(
        'GITLAB_API_TOKEN',
        f'get your own token at {endpoint}/-/profile/personal_access_tokens',
    )
    gl = gitlab.Gitlab(endpoint, private_token=token)
    return gl


def validate_repo_name(ctx, param, value):
    """
    >>> validate_repo_name(None, None, 'dev/avln-server')
    'dev/avln-server'
    >>> validate_repo_name(None, None, 'foo')
    Traceback (most recent call last):
      ...
    click.exceptions.BadParameter: specify project name in format [group_name]/[repo_name]
    """
    if REPO_NAME_GEX.match(value):
        return value
    raise BadParameter('specify project name in format [group_name]/[repo_name]')


def fetch_chart(project_name, output_dir=CWD):
    gl = get_gitlab()
    project = gl.projects.get(project_name)
    head = project.commits.list(per_page=1)[0]
    chart_path = join(output_dir, f'{project_name}/chart')
    pathlib.Path(chart_path).mkdir(parents=True, exist_ok=False)
    for fdic in project.repository_tree('chart', all=True):
        if fdic['type'] == 'tree':
            continue
        path = fdic['path']
        fname = path.split('/')[-1]
        if not fname.startswith('values'):
            continue
        values_file = project.files.get(path, head.id)
        dest = join(output_dir, f'{project_name}/{path}')
        debug(f'writing file to {dest}')
        with open(dest, 'wb') as f:
            f.write(values_file.decode())

    with change_dir(join(output_dir, project_name)):
        lain_('--ignore-lint', 'init', '--template-only')
