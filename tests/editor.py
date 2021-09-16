#!/usr/bin/env python
import os
import sys

from ruamel.yaml import YAML


yaml = YAML()
target = sys.argv[1]
with open(target) as f:
    content = yaml.load(f.read())

os.unlink(target)
content['data']['SURPRISE'] = os.environ['PWD']
with open(target, 'w') as f:
    yaml.dump(content, f)
