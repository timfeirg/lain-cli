#!/usr/bin/env python
from pathlib import Path

from setuptools import find_packages, setup

from lain_cli import __version__, package_name

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
    'tenacity>=6.0.0',
    'python-gitlab>=2.4.0',
    'sentry-sdk>=1.0.0',
    'psutil>=5.8.0',
    'cachetools>=5.2.0',
    'cryptography>=37.0.2',
]
tencent_requirements = ['tencentcloud-sdk-python>=3.0.130']
aliyun_requirements = [
    'aliyun-python-sdk-cr>=3.0.1',
    'aliyun-python-sdk-core>=2.13.15',
    'aliyun-python-sdk-cloudapi>=4.9.2',
]
requirements.extend(tencent_requirements)
requirements.extend(aliyun_requirements)
tests_requirements = [
    'pytest>=5.2.4',
    'pytest-cov>=2.10.1',
    'pytest-mock>=3.1.0',
    'pytest-ordering>=0.6',
    'pytest-env>=0.6.2',
]
all_requirements = tests_requirements
this_directory = Path(__file__).parent
long_description = (this_directory / 'README.md').read_text()
setup(
    name=package_name,
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/timfeirg/lain-cli',
    python_requires='>=3.9',
    version=__version__,
    packages=find_packages(),
    include_package_data=True,
    entry_points={'console_scripts': ['lain=lain_cli.lain:main']},
    install_requires=requirements,
    zip_safe=False,
    extras_require={
        'all': all_requirements,
        'tests': tests_requirements,
    },
)
