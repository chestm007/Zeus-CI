from enum import Enum
from typing import List

import github_webhook
from flask import Flask

from zeus_ci.runner import Status
from zeus_ci.persistence import SqliteConnection, Build

WebhookProviders = Enum('WebhookProviders', 'github')


def start(host, port, providers: List[WebhookProviders]):
    app = Flask(__name__)
    for provider in providers:
        if provider == WebhookProviders.github:
            make_github_webhook(app)

    @app.route('/')
    def root():
        return 200

    app.run(host=host, port=port)


def make_github_webhook(app):
    webhook = github_webhook.Webhook(app, endpoint='/github-webhook/')

    @webhook.hook()
    def on_push(data):
        if data.get('ref'):
            if data.get('ref_type', '') == 'tag':
                return

            persistence = SqliteConnection()
            build = Build(ref=data['ref'],
                          repo=data['repository']['full_name'],
                          json_blob=data,
                          status=Status.created)
            persistence.insert_build(build)


if __name__ == '__main__':
    start('0.0.0.0', 4230, [WebhookProviders.github])
