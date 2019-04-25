from enum import Enum
from typing import List

import github_webhook
from flask import Flask


WebhookProviders = Enum('WebhookProviders', 'github')


def start(host, port, providers: List[WebhookProviders]):

    app = Flask(__name__)
    for provider in providers:
        if provider == WebhookProviders.github:
            make_github_webhook(app)

    @app.route('/')
    def root():
        return 'Hai'

    app.run(host=host, port=port)


def make_github_webhook(app):
    webhook = github_webhook.Webhook(app, endpoint='/github-webhook/')

    @webhook.hook()
    def on_push(data):
        print('Got push with: {0}'.format(data))


if __name__ == '__main__':
    start('0.0.0.0', 4230, [WebhookProviders.github])
    print('ran')
