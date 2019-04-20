from distutils.core import setup

from setuptools import find_packages

with open('README.md') as f:
    readme = f.read()


setup(
    name='lcircle',
    version='PROJECTVERSION',
    packages=find_packages(),
    url='https://github.com/chestm007/lcircle',
    license='GPL-2.0',
    author='Max Chesterfield',
    author_email='chestm007@hotmail.com',
    maintainer='Max Chesterfield',
    maintainer_email='chestm007@hotmail.com',
    description='local test runner for circleci',
    long_description=readme,
    install_requires=[
        'pyyaml',
    ],
    entry_points="""
        [console_scripts]
        lcircle=lcircle.lcircle:main
    """,
)