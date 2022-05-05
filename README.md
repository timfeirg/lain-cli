## lain

[![readthedocs](https://readthedocs.org/projects/pip/badge/?version=latest&style=plastic)](https://lain-cli.readthedocs.io/en/latest/) [![CircleCI](https://circleci.com/gh/timfeirg/lain-cli.svg?style=svg)](https://circleci.com/gh/timfeirg/lain-cli) [![codecov](https://codecov.io/gh/timfeirg/lain-cli/branch/master/graph/badge.svg?token=A6153W38P4)](https://codecov.io/gh/timfeirg/lain-cli)

lain is a DevOps solution, but really, it just helps you with kubectl / helm / docker.

[![asciicast](https://asciinema.org/a/iLCiMoE4SDTyjcspXYfXGSkeO.svg)](https://asciinema.org/a/iLCiMoE4SDTyjcspXYfXGSkeO)

## Installation / Adoption

The recommended way to use lain is to [maintain an internal fork for your team](https://lain-cli.readthedocs.io/en/latest/dev.html#lain), this may be too much, you can still try out lain with the following steps:

* Install from PyPI: `pip install -U lain`
* Write cluster values, according to docs [here](https://lain-cli.readthedocs.io/en/latest/dev.html#cluster-values), and examples [here](https://github.com/timfeirg/lain-cli/tree/master/lain_cli/cluster_values), so that lain knows how to talk to your Kubernetes cluster
* Set `CLUSTER_VALUES_DIR` to the directory that contains all your cluster values
* Start using lain

## Links

* Documentation (Chinese): [lain-cli.readthedocs.io](https://lain-cli.readthedocs.io/en/latest/)
