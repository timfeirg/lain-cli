import asyncio
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from operator import itemgetter
from subprocess import list2cmdline

import requests
from humanfriendly import parse_size
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout

from lain_cli.utils import (
    DEFAULT_BACKEND_RESPONSE,
    context,
    ensure_str,
    get_pods,
    kubectl,
    parse_kubernetes_cpu,
    parse_multi_timespan,
    parse_podline,
    parse_ready,
    rc,
    tell_screen_height,
    tell_pod_deploy_name,
    tell_pods_count,
    template_env,
)

CONTENT_VENDERER = {
    'event_text': '',
    'ingress_text': '',
    'pod_text': '',
    'top_text': '',
    'bad_pods': [],
    'node_text': '',
}


def set_content(k, v):
    CONTENT_VENDERER[k] = v


async def refresh_events_text():
    """display events for weird pods"""
    bad_pods = CONTENT_VENDERER['bad_pods']
    if not bad_pods:
        CONTENT_VENDERER['event_text'] = 'no weird pods found'
        return
    cmd = []
    for podline in bad_pods[1:]:
        pod_name, ready_str, status, restarts, age, *_ = parse_podline(podline)
        if status == 'Completed':
            continue
        if status == 'Pending':
            cmd = [
                'get',
                'pod',
                f'{pod_name}',
                '-ojsonpath={.status.containerStatuses..message}',
            ]
            break
        age = parse_multi_timespan(age)
        if status == 'ContainerCreating' and age > 30:
            cmd = ['get', 'events', f'--field-selector=involvedObject.name={pod_name}']
            break
        if (
            status == 'CrashLoopBackOff'
            or not parse_ready(ready_str)
            or int(restarts) > 0
        ):
            cmd = ['logs', '--tail=50', f'{pod_name}']
            break

    if cmd:
        res = kubectl(*cmd, capture_output=True, check=False)
        CONTENT_VENDERER['event_text'] = ensure_str(res.stdout) or ensure_str(
            res.stderr
        )
        return

    CONTENT_VENDERER['event_text'] = 'no weird pods found'


def build_app_status_command():
    ctx = context()
    appname = ctx.obj['appname']
    pod_cmd = [
        'get',
        'pod',
        '-owide',
        # add this sort so that abnormal pods appear on top
        '--sort-by={.status.phase}',
        '-lapp.kubernetes.io/name={appname}',
    ]
    ctx.obj['watch_pod_command'] = pod_cmd
    if tell_pods_count() > 13:
        ctx.obj['too_many_pods'] = True
        ctx.obj[
            'watch_pod_title'
        ] = f'(digested, only showing weird pods) k {list2cmdline(pod_cmd)}'
    else:
        ctx.obj['too_many_pods'] = False
        ctx.obj['watch_pod_title'] = f'k {list2cmdline(pod_cmd)}'

    top_cmd = ['top', 'po', '-l', f'app.kubernetes.io/name={appname}']
    ctx.obj['watch_top_command'] = top_cmd
    if ctx.obj['too_many_pods']:
        ctx.obj['watch_top_title'] = f'(digested) k {list2cmdline(top_cmd)}'
    else:
        ctx.obj['watch_top_title'] = f'k {list2cmdline(top_cmd)}'


def pod_text(too_many_pods=None):
    ctx = context()
    appname = ctx.obj['appname']
    if too_many_pods is None:
        too_many_pods = ctx.obj['too_many_pods']

    res, pods = get_pods(
        appname=appname, headers=True, show_only_bad_pods=too_many_pods
    )
    if rc(res):
        return ensure_str(res.stderr)
    CONTENT_VENDERER['bad_pods'] = pods
    report = '\n'.join(pods)
    return report


async def refresh_pod_text():
    set_content('pod_text', pod_text())


async def refresh_top_text():
    set_content('top_text', top_text())


def kubectl_top_digest(stdout):
    lines = stdout.splitlines()
    procs_group = defaultdict(list)
    for l in lines[1:]:
        pod_name, cpu, memory = l.split()
        if memory.startswith('0'):
            continue
        deploy_name = tell_pod_deploy_name(pod_name)
        procs_group[deploy_name].append(
            {'memory': parse_size(memory), 'cpu': parse_kubernetes_cpu(cpu), 'line': l}
        )

    pods_digest = set()
    for pods in procs_group.values():
        by_cpu = sorted(pods, key=itemgetter('cpu'))
        pods_digest |= {by_cpu[0]['line'], by_cpu[-1]['line']}
        by_mem = sorted(pods, key=itemgetter('memory'))
        pods_digest |= {by_mem[0]['line'], by_mem[-1]['line']}

    report = '\n'.join(lines[0:0] + sorted(list(pods_digest)))
    return report


def top_text(too_many_pods=None):
    """display kubectl top results"""
    ctx = context()
    cmd = ctx.obj['watch_top_command']
    res = kubectl(*cmd, timeout=9, capture_output=True, check=False)
    stdout = ensure_str(res.stdout)
    if too_many_pods is None:
        too_many_pods = ctx.obj['too_many_pods']

    if stdout and too_many_pods:
        report = kubectl_top_digest(stdout)
    else:
        report = stdout or ensure_str(res.stderr)

    return report


def test_url(url):
    try:
        res = requests.get(url, timeout=2)
    except Exception as e:
        return e
    return res


ingress_text_str = '''{% for res in results %}
{% if res.status is defined %}
{{ res.url }}   {{ res.status }}   {{ res.text | brief }}
{% endif %}
{% endfor %}
'''
ingress_text_template = template_env.from_string(ingress_text_str)


async def refresh_ingress_text():
    set_content('ingress_text', ingress_text())


def ingress_text():
    ctx = context()
    urls = ctx.obj.get('urls')
    if not urls:
        return ''
    rl = []
    results = []

    def tidy_report(re):
        if not re.request:
            return ''
        report = {'url': re.request.url}
        if isinstance(re, requests.Response):
            report.update(
                {
                    'status': re.status_code,
                    'text': re.text,
                }
            )
        elif isinstance(re, requests.exceptions.RequestException):
            report.update(
                {
                    'status': re.__class__.__name__,
                    'text': str(re),
                }
            )
        else:
            raise ValueError(f'cannot process this request result: {re}')
        return report

    # why use ThreadPoolExecutor?
    # because we can't use loop.run_until_complete in the main thread
    # and why is that?
    # because prompt_toolkit application itself runs in a asyncio eventloop
    # you can't tell the current eventloop to run something for you if the
    # invoker itself lives in that eventloop
    # ref: https://bugs.python.org/issue22239
    with ThreadPoolExecutor(max_workers=len(urls)) as executor:
        for url in urls:
            rl.append(executor.submit(test_url, url))

        for future in as_completed(rl):
            results.append(tidy_report(future.result()))

    render_ctx = {'results': sorted(results, key=itemgetter('url'))}
    res = ingress_text_template.render(**render_ctx)
    return res


Win = partial(Window, wrap_lines=True)
Title = partial(FormattedTextControl, style='fg:GreenYellow')


async def refresh_content():
    while True:
        await asyncio.wait(
            [
                refresh_pod_text(),
                refresh_ingress_text(),
                refresh_events_text(),
                refresh_top_text(),
            ]
        )
        get_app().invalidate()
        await asyncio.sleep(0.1)


def build_app_status():
    ctx = context()
    build_app_status_command()
    # building pods container
    pod_text_control = FormattedTextControl(text=lambda: CONTENT_VENDERER['pod_text'])
    pod_win = Win(content=pod_text_control)
    pod_title = ctx.obj['watch_pod_title']
    pod_container = HSplit(
        [
            Win(
                height=1,
                content=Title(pod_title),
            ),
            pod_win,
        ]
    )
    # building top container
    top_text_control = FormattedTextControl(text=lambda: CONTENT_VENDERER['top_text'])
    top_win = Win(content=top_text_control)
    top_title = ctx.obj['watch_top_title']
    top_container = HSplit(
        [
            Win(
                height=1,
                content=Title(top_title),
            ),
            top_win,
        ]
    )
    # building events container
    events_text_control = FormattedTextControl(
        text=lambda: CONTENT_VENDERER['event_text']
    )
    events_window = Win(content=events_text_control)
    events_container = HSplit(
        [
            Win(
                height=1,
                content=Title('events and messages for pods in weird states'),
            ),
            events_window,
        ]
    )
    parts = [pod_container, top_container, events_container]
    # building ingress container
    urls = ctx.obj.get('urls')
    if urls:
        ingress_text_control = FormattedTextControl(
            text=lambda: CONTENT_VENDERER['ingress_text']
        )
        ingress_window = Win(content=ingress_text_control, height=len(urls) + 3)
        ingress_container = HSplit(
            [
                Win(height=1, content=Title('url requests')),
                ingress_window,
            ]
        )
        parts.append(ingress_container)

    # building root container
    root_container = HSplit(parts)
    kb = KeyBindings()

    @kb.add('c-c', eager=True)
    @kb.add('c-q', eager=True)
    def _(event):
        event.app.exit()

    app = Application(
        key_bindings=kb,
        layout=Layout(root_container),
        full_screen=True,
    )
    app.create_background_task(refresh_content())
    return app


def display_app_status():
    prompt_app = build_app_status()
    prompt_app.run()


def build_cluster_status_command():
    ctx = context()
    pod_cmd = ctx.obj['watch_bad_pod_command'] = [
        'get',
        'po',
        '--all-namespaces',
        '-owide',
    ]
    ctx.obj['watch_bad_pod_title'] = f'k {list2cmdline(pod_cmd)}'


async def refresh_bad_pod_text():
    res, pods = get_pods(headers=True, show_only_bad_pods=True)
    set_content('pod_text', '\n'.join(pods) or ensure_str(res.stderr))


def bad_node_text():
    ctx = context()
    cmd = ctx.obj['watch_node_command'] = ['get', 'node', '--no-headers']
    res = kubectl(*cmd, timeout=2, capture_output=True, check=False)
    if rc(res):
        return ensure_str(res.stderr)
    all_nodes = ensure_str(res.stdout)
    bad_nodes = [line for line in all_nodes.splitlines() if ' Ready ' not in line]
    return '\n'.join(bad_nodes)


async def refresh_bad_node_text():
    set_content('node_text', bad_node_text())


async def refresh_global_ingress_text():
    set_content('ingress_text', global_ingress_text())


def global_ingress_text():
    ctx = context()
    global_urls = ctx.obj['global_urls']
    if not global_urls:
        return ''
    rl = []
    results = []

    def tidy_report(re):
        if not re.request:
            return ''
        report = {'url': re.request.url}
        if isinstance(re, requests.Response):
            code = re.status_code
            if code >= 502 or (
                code == 404 and re.text.strip() == DEFAULT_BACKEND_RESPONSE
            ):
                report.update(
                    {
                        'status': re.status_code,
                        'text': re.text,
                    }
                )
        elif isinstance(re, requests.exceptions.RequestException):
            report.update(
                {
                    'status': re.__class__.__name__,
                    'text': str(re),
                }
            )
        else:
            raise ValueError(f'cannot process this request result: {re}')
        return report

    simple = ctx.obj.get('simple')
    with ThreadPoolExecutor(max_workers=len(global_urls)) as executor:
        for url in global_urls:
            rl.append(executor.submit(test_url, url))

        for future in as_completed(rl):
            single_report = tidy_report(future.result())
            if not single_report or not single_report.get('status'):
                continue
            if simple or len(results) < tell_screen_height(0.4):
                results.append(single_report)

    render_ctx = {'results': sorted(results, key=itemgetter('url'))}
    res = ingress_text_template.render(**render_ctx)
    return res


async def refresh_admin_content():
    while True:
        await asyncio.wait(
            [
                refresh_bad_pod_text(),
                refresh_bad_node_text(),
                refresh_global_ingress_text(),
            ]
        )
        get_app().invalidate()
        await asyncio.sleep(0.1)


def build_cluster_status():
    ctx = context()
    build_cluster_status_command()
    # building pods container
    bad_pod_text_control = FormattedTextControl(
        text=lambda: CONTENT_VENDERER['pod_text']
    )
    bad_pod_win = Win(content=bad_pod_text_control)
    bad_pod_title = ctx.obj['watch_bad_pod_title']
    bad_pod_container = HSplit(
        [
            Win(
                height=1,
                content=Title(bad_pod_title),
            ),
            bad_pod_win,
        ]
    )
    # building nodes container
    bad_node_text_control = FormattedTextControl(
        text=lambda: CONTENT_VENDERER['node_text']
    )
    bad_node_window = Win(content=bad_node_text_control)
    bad_node_container = HSplit(
        [
            Win(
                height=1,
                content=Title('bad nodes'),
            ),
            bad_node_window,
        ]
    )
    parts = [bad_pod_container, bad_node_container]
    global_urls = ctx.obj.get('global_urls')
    if global_urls:
        ingress_text_control = FormattedTextControl(
            text=lambda: CONTENT_VENDERER['ingress_text']
        )
        ingress_window = Win(
            content=ingress_text_control, height=lambda: tell_screen_height(0.4)
        )
        ingress_container = HSplit(
            [
                Win(height=1, content=Title('bad url requests')),
                ingress_window,
            ]
        )
        parts.append(ingress_container)

    # building root container
    root_container = HSplit(parts)
    kb = KeyBindings()

    @kb.add('c-c', eager=True)
    @kb.add('c-q', eager=True)
    def _(event):
        event.app.exit()

    app = Application(
        key_bindings=kb,
        layout=Layout(root_container),
        full_screen=True,
    )
    app.create_background_task(refresh_admin_content())
    return app


def display_cluster_status():
    prompt_app = build_cluster_status()
    prompt_app.run()
