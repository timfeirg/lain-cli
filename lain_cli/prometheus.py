import json
from datetime import datetime, timedelta, timezone
from statistics import StatisticsError, quantiles

import click
from humanfriendly import parse_timespan

from lain_cli.utils import (
    RequestClientMixin,
    ensure_str,
    tell_cluster_config,
    warn,
    error,
)

LAIN_LINT_PROMETHEUS_QUERY_RANGE = '7d'
LAIN_LINT_PROMETHEUS_QUERY_STEP = int(
    int(parse_timespan(LAIN_LINT_PROMETHEUS_QUERY_RANGE)) / 1440
)


class Prometheus(RequestClientMixin):
    timeout = 20

    def __init__(self, endpoint=None):
        if not endpoint:
            cc = tell_cluster_config()
            endpoint = cc.get('prometheus')
            if not endpoint:
                raise click.Abort(f'prometheus not provided in cluster config: {cc}')

        self.endpoint = endpoint

    @staticmethod
    def format_time(dt):
        if isinstance(dt, str):
            return dt
        return dt.isoformat()

    def query_cpu(self, appname, proc_name, **kwargs):
        cc = tell_cluster_config()
        query_template = cc.get('pql_template', {}).get('cpu')
        if not query_template:
            raise ValueError('pql_template.cpu not configured in cluster config')
        q = query_template.format(
            appname=appname, proc_name=proc_name, range=LAIN_LINT_PROMETHEUS_QUERY_RANGE
        )
        kwargs.setdefault('step', LAIN_LINT_PROMETHEUS_QUERY_STEP)
        kwargs['end'] = datetime.now(timezone.utc)
        res = self.query(q, **kwargs)
        return res

    def cpu_p95(self, appname, proc_name, **kwargs):
        cpu_result = self.query_cpu(appname, proc_name)
        # [{'metric': {}, 'value': [1595486084.053, '4.990567343235413']}]
        if cpu_result:
            cpu_top_list = [int(float(p[-1])) for p in cpu_result[0]['values']]
            cnt = len(cpu_top_list)
            if cpu_top_list.count(0) / cnt > 0.7:
                warn(f'lint suggestions might not be accurate for {proc_name}')

            try:
                cpu_top = int(quantiles(cpu_top_list, n=10)[-1])
            except StatisticsError:
                cpu_top = 5
        else:
            cpu_top = 5

        return max([cpu_top, 5])

    def memory_quantile(self, appname, proc_name, **kwargs):
        cc = tell_cluster_config()
        query_template = cc.get('pql_template', {}).get('memory_quantile')
        if not query_template:
            raise ValueError(
                'pql_template.memory_quantile not configured in cluster config'
            )
        q = query_template.format(
            appname=appname, proc_name=proc_name, range=LAIN_LINT_PROMETHEUS_QUERY_RANGE
        )
        kwargs.setdefault('step', LAIN_LINT_PROMETHEUS_QUERY_STEP)
        res = self.query(q, **kwargs)
        if not res:
            return
        # [{'metric': {}, 'value': [1583388354.31, '744079360']}]
        memory_quantile = int(float(res[0]['value'][-1]))
        return memory_quantile

    def query(self, query, start=None, end=None, step=None, timeout=20):
        # https://prometheus.io/docs/prometheus/latest/querying/api/#range-queries
        data = {
            'query': query,
            'timeout': timeout,
        }
        if start or end:
            if not start:
                start = end - timedelta(days=1)

            if not end:
                end = datetime.now(timezone.utc).isoformat()

            if not step:
                step = 60

            path = '/api/v1/query_range'
            data.update(
                {
                    'start': self.format_time(start),
                    'end': self.format_time(end),
                    'step': step,
                }
            )
        else:
            path = '/api/v1/query'

        res = self.post(path, data=data)
        try:
            responson = res.json()
        except json.decoder.JSONDecodeError as e:
            raise ValueError(
                'cannot decode this shit: {}'.format(ensure_str(res.text))
            ) from e
        if responson.get('status') == 'error':
            raise ValueError(responson['error'])
        return responson['data']['result']


class Alertmanager(RequestClientMixin):
    """https://github.com/prometheus/alertmanager/blob/main/api/v2/openapi.yaml"""

    timeout = 20

    def __init__(self, endpoint=None):
        if not endpoint:
            cc = tell_cluster_config()
            endpoint = cc.get('alertmanager')
            if not endpoint:
                raise click.Abort(f'alertmanager not provided in cluster config: {cc}')

        self.endpoint = endpoint.rstrip('/')

    def post_alerts(self):
        payload = [
            {
                'labels': {'label': 'value'},
                'annotations': {'label': 'value'},
                'generatorURL': f'{self.endpoint}/<generating_expression>',
            },
        ]
        res = self.post('/api/v2/alerts', json=payload)
        if res.status_code >= 400:
            error(res.text)
