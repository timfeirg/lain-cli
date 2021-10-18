from lain_cli.utils import format_kubernetes_memory, parse_size

# lain lint config
MEMORY_FORGIVING_COEFFICIENT = 1.13
# 如果你用的内存不多, 放过你
MEMORY_FORGIVING_POOR_MEMORY = parse_size('256Mi', binary=True)


def suggest_cpu_limits(limits):
    if limits < 1000:
        return '1000m'
    return False


def suggest_cpu_requests(requests, top):
    if requests < top - 300 or requests > top + 300:
        suggest_str = f'{top}m'
        return suggest_str
    return False


def suggest_memory_requests(requests, top):
    # 对于内存需求太穷的应用, 就不麻烦人家了
    if top < MEMORY_FORGIVING_POOR_MEMORY and requests < MEMORY_FORGIVING_POOR_MEMORY:
        return False
    if (
        top * MEMORY_FORGIVING_COEFFICIENT < requests
        or top / MEMORY_FORGIVING_COEFFICIENT > requests
    ):
        memory_requests_suggest_str = format_kubernetes_memory(top)
        return memory_requests_suggest_str

    return False


def suggest_memory_limits(limits, top, proc=None):
    proc = proc or {}
    if proc.get('replicaCount', 0) > 5:
        top_to_limits = 1.3
        margin = parse_size('50Mi', binary=True)
    else:
        top_to_limits = 2.5
        margin = parse_size('1Gi', binary=True)

    limits_suggest = top * top_to_limits
    if abs(limits_suggest - limits) < margin:
        return False
    limits_suggest_str = format_kubernetes_memory(limits_suggest)
    if (
        limits_suggest * MEMORY_FORGIVING_COEFFICIENT < limits
        or limits_suggest / MEMORY_FORGIVING_COEFFICIENT > limits
    ):
        return limits_suggest_str
    return False
