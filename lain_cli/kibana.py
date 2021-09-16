from datetime import datetime, timedelta
from time import sleep

from humanfriendly import parse_timespan

from lain_cli.utils import RequestClientMixin, debug, error, tell_cluster_config


class Kibana(RequestClientMixin):

    timezone = 'Asia/Shanghai'
    timeout = 40

    def __init__(self):
        cc = tell_cluster_config()
        kibana_host = cc.get('kibana')
        if not kibana_host:
            error('kibana not configured for this cluster', exit=1)

        self.endpoint = f'http://{kibana_host}'
        self.timeout_ms = self.timeout * 1000
        self.headers = {
            'kbn-xsrf': 'true',
        }

    def request(self, *args, **kwargs):
        res = super().request(*args, **kwargs)
        res.raise_for_status()
        return res

    @staticmethod
    def isoformat(dt):
        return f'{dt.isoformat()}Z'

    def count_records_for_host(
        self, host=None, ingress_class='lain-internal', period='7d'
    ):
        path = '/internal/search/es'
        start = datetime.utcnow()
        delta = timedelta(seconds=parse_timespan(period))
        end = start - delta
        if ingress_class == 'lain-internal':
            index_pattern = 'nginx-internal-*'
        elif ingress_class == 'lain-external':
            index_pattern = 'nginx-external-*'
        else:
            raise ValueError(f'weird ingress_class: {ingress_class}')

        # query copied from browser
        query = {
            'params': {
                'body': {
                    '_source': {'excludes': []},
                    'aggs': {
                        '2': {
                            'date_histogram': {
                                'field': 'ts',
                                'fixed_interval': '3h',
                                'min_doc_count': 1,
                                'time_zone': self.timezone,
                            }
                        }
                    },
                    'docvalue_fields': [
                        {'field': '@timestamp', 'format': 'date_time'},
                        {'field': 'ts', 'format': 'date_time'},
                    ],
                    'highlight': {
                        'fields': {'*': {}},
                        'fragment_size': 2147483647,
                        'post_tags': ['@/kibana-highlighted-field@'],
                        'pre_tags': ['@kibana-highlighted-field@'],
                    },
                    'query': {
                        'bool': {
                            'filter': [
                                {
                                    'range': {
                                        'ts': {
                                            'format': 'strict_date_optional_time',
                                            'lte': self.isoformat(start),
                                            'gte': self.isoformat(end),
                                        }
                                    }
                                }
                            ],
                            'must': [
                                {
                                    'query_string': {
                                        'analyze_wildcard': True,
                                        'query': f'vhost:"{host}"',
                                        'time_zone': self.timezone,
                                    }
                                }
                            ],
                            'must_not': [],
                            'should': [],
                        }
                    },
                    'script_fields': {},
                    'size': 500,
                    'sort': [{'ts': {'order': 'desc', 'unmapped_type': 'boolean'}}],
                    'stored_fields': ['*'],
                    'version': True,
                },
                'ignoreThrottled': True,
                'ignore_throttled': True,
                'ignore_unavailable': True,
                'index': index_pattern,
                # https://github.com/elastic/kibana/blob/master/src/plugins/data/public/search/es_search/get_es_preference.ts#L25
                'preference': None,
                'rest_total_hits_as_int': True,
                'timeout': f'{self.timeout_ms}ms',
            },
            'serverStrategy': 'es',
        }
        res = self.post(path, json=query)
        responson = res.json()
        tries = 9
        request_id = responson.get('id')  # 没给 id 的话, 说明查询已经结束, 不用轮询结果了
        if not request_id:
            while responson['loaded'] != responson['total'] and tries:
                debug(f'polling kibana search results: {request_id}')
                sleep(3)
                res = self.post(path, json={'id': request_id})
                responson = res.json()
                tries -= 1

        try:
            count = responson['rawResponse']['hits']['total']
        except KeyError:
            return 0
        return count
