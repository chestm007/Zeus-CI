from distutils.core import setup

from setuptools import find_packages

with open('README.md') as f:
    readme = f.read()


setup(
    name='Zeus-CI',
    version='PROJECTVERSION',
    packages=find_packages(),
    url='https://github.com/chestm007/lcircle',
    license='GPL-2.0',
    author='Max Chesterfield',
    author_email='chestm007@hotmail.com',
    maintainer='Max Chesterfield',
    maintainer_email='chestm007@hotmail.com',
    description='python CI server that tries to not suck',
    long_description=readme,
    install_requires=[
        'pyyaml',
        'flask',
        'sqlalchemy',
        'pygithub',
        'faust',
        'rpyc',
        'github-webhook'
    ],
    extras_require={
        'github_status_reporting': ['github'],
        'github_webhook_listener': ['github-webhook'],
        'resource_allocator': ['rpyc'],
    },
    entry_points="""
        [console_scripts]
        zeus-ci-runner=zeus_ci.runner:main
        zeus-ci-buildcoordinator=zeus_ci.build_coordinator:main
        zeus-ci-listener=zeus_ci.listeners:main
        zeus-ci-resource-allocator=zeus_ci.resource_allocator:main
        zeus-cli=zeus_ci.cli:main
    """,
)
