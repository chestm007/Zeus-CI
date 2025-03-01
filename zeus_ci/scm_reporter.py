from collections import namedtuple
from enum import Enum

from zeus_ci import logger
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
        from github import Github as PyGithub
        self.client = PyGithub(*auth)

    def update_status(self, build: Build, status: GithubStatus):
        repo = self.client.get_repo(build.repo.name)
        logger.debug(f'loading data for build {build} to repo {repo}')
        if not repo:
            raise FileNotFoundError  # TODO: make this something better

        commit = repo.get_commit(sha=build.commit)
        logger.debug(f'Applies to commit: {commit}')
        if not commit:
            raise AttributeError  # TODO: come on man, these are getting ridiculous

        logger.info(f'updating commit status: {status.name}, {repo.name}')

        commit.create_status(
            state=status.name,
        )
