import argparse
from enum import Enum
from typing import List

from flask import Flask
from sqlalchemy.orm.exc import NoResultFound

from zeus_ci import logger
from zeus_ci import Status, Config
from zeus_ci.persistence import Database, Build, Repo, User
from zeus_ci.scm_reporter import Github, TokenAuth, GithubStatus

WebhookProviders = Enum('WebhookProviders', 'github')


def start(host, port, providers: List[WebhookProviders],
          sqlalchemy_args: dict = None):

    logger.info('starting...')
    app = Flask(__name__)

    database = Database(**sqlalchemy_args)

    for provider in providers:
        logger.info('starting webhook provider for %s', provider.name)
        if provider == WebhookProviders.github:
            make_github_webhook(app, database)

    @app.route('/')
    def root():
        return

    app.run(host=host, port=port)


def make_github_webhook(app, database):
    import github_webhook
    webhook = github_webhook.Webhook(app, endpoint='/github-webhook/')

    @webhook.hook()
    def on_push(data):
        logger.debug('recieved push event\n %s', data)
        if data.get('ref'):
            if data.get('ref_type', '') == 'tag':
                return
            with database.get_session() as session:

                repo_name = data['repository']['full_name']
                username = data['sender']['login']

                try:
                    user = session.query(User).filter_by(username=username).one()
                except NoResultFound:
                    logger.debug('adding new user: %s', username)
                    user = User(username=username)
                    session.add(user)

                try:
                    repo = session.query(Repo).filter_by(name=repo_name).one()
                except NoResultFound:
                    logger.debug('adding new repo: %s', username)
                    repo = Repo(name=repo_name,
                                username=user.username,
                                scm='github')
                    session.add(repo)

                build = Build(ref=data['ref'],
                              repo_name=repo.name,
                              commit=data['after'],
                              json=data,
                              status=Status.created)

                repo.builds.append(build)

                session.commit()

                github = Github(TokenAuth(user.token))
                github.update_status(build, GithubStatus.pending)


def main():
    parser = argparse.ArgumentParser(description='Webhook listener for Zeus-CI')
    parser.add_argument('--listen-address', type=str, default='0.0.0.0')
    parser.add_argument('--port', type=int, default=4230)
    parser.add_argument('--sqlalchemy-protocol', type=str)
    parser.add_argument('--sqlalchemy-protocol-args', type=str)
    args = parser.parse_args()
    config = Config()

    sqlalchemy_args = dict(
        protocol=args.sqlalchemy_protocol or config.database.get('protocol'),
        protocol_args=args.sqlalchemy_protocol_args or config.database.get('args')
    )
    logger.info(f'Using sql config: {sqlalchemy_args}')
    start(args.listen_address, args.port, [WebhookProviders.github],
          sqlalchemy_args=sqlalchemy_args)


if __name__ == '__main__':
    main()
