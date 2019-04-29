import logging
from collections import namedtuple
from enum import Enum

from github import Github as PyGithub

from zeus_ci.persistence import Build

TokenAuth = namedtuple('TokenAuth', ('access_token', ))
EnterpriseAuth = namedtuple('EnterpriseAuth', ('base_url', 'token'))

GithubStatus = Enum('status', 'error failure pending success')


class Github:

    status_descriptions = {
        GithubStatus.error: 'Error encountered during build',
        GithubStatus.failure: 'Build failed',
        GithubStatus.pending: 'Build is currently running',
        GithubStatus.success: "Build succeeded!"
    }  # TODO: consider scm agnostic global map

    def __init__(self, auth: namedtuple):
        self.client = PyGithub(*auth)

    def update_status(self, build: Build, status: GithubStatus):
        repo = self.client.get_repo(build.repo.name)
        if not repo:
            raise FileNotFoundError  # TODO: make this something better

        commit = repo.get_commit(sha=build.commit)
        if not commit:
            raise AttributeError  # TODO: come on man, these are getting ridiculous

        commit.create_status(
            state=status.name,
            target_url='https://fooCI.com',  # TODO: load this from zeus-ci config file
            description=self.status_descriptions[status],
            context=repo.name
        )
