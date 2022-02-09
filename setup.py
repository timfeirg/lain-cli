#!/usr/bin/env python
from setuptools import find_packages, setup

from lain_cli import __version__

ENTRY_POINTS = """
[console_scripts]
lain = lain_cli.lain:main
"""
requirements = [
    'pip>=22.0',
    'ruamel.yaml>=0.17.10',
    'requests',
    'humanfriendly>=4.16.1',
    'click>=8.0',
    'jinja2>=3.0',
    'prompt-toolkit>=3.0.0',
    'packaging>=19.2',
    'marshmallow>=3.13.0',
    'tencentcloud-sdk-python>=3.0.130',
    'aliyun-python-sdk-cr>=3.0.1',
    'aliyun-python-sdk-core>=2.13.15',
    'tenacity>=6.0.0',
    'python-gitlab>=2.4.0',
    'sentry-sdk>=1.0.0',
    'psutil>=5.8.0',
]
tests_requirements = [
    'pytest>=5.2.4',
    'pytest-cov>=2.10.1',
    'pytest-mock>=3.1.0',
    'pytest-ordering>=0.6',
    'pytest-env>=0.6.2',
]
all_requirements = tests_requirements

setup(
    name='lain_cli',
    url='https://github.com/yashihq/lain-cli',
    python_requires='>=3.8',
    version=__version__,
    packages=find_packages(),
    include_package_data=True,
    entry_points=ENTRY_POINTS,
    install_requires=requirements,
    zip_safe=False,
    extras_require={
        'all': all_requirements,
        'tests': tests_requirements,
    },
)
