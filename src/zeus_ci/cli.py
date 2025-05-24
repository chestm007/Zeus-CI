import json

import click

from zeus_ci.persistence import Database, Build, User, Repo
from zeus_ci import Status


@click.group()
@click.option('--sqlalchemy-protocol', type=str)
@click.option('--sqlalchemy-protocol-args', type=str)
@click.pass_context
def main(ctx, sqlalchemy_protocol, sqlalchemy_protocol_args):
    ctx.ensure_object(dict)
    database = Database(protocol=sqlalchemy_protocol, protocol_args=sqlalchemy_protocol_args)
    ctx.obj['session'] = database.get_session()


@main.group()
def users():
    pass


@users.command()
@click.pass_context
def list(ctx):
    session = ctx.obj['session']
    _users = session.query(User).all()
    for user in _users:
        click.echo(user)


@users.command()
@click.argument('username')
@click.argument('token')
@click.pass_context
def add_token(ctx, username, token):
    session = ctx.obj['session']
    user = session.query(User).filter_by(username=username).one()
    user.token = token
    session.commit()


@main.group()
def repos():
    pass


@repos.command()
@click.argument('repo')
@click.option('--add', multiple=True)
@click.option('--list', is_flag=True, help='list envvars')
@click.pass_context
def envvars(ctx, repo, add, **kwargs):
    session = ctx.obj['session']
    repo = session.query(Repo).filter_by(name=repo).one()
    if add:
        for var in add:
            if not repo.env_vars:
                repo.env_vars = []
            repo.add_envvar(json.loads(var))
        session.commit()

    if kwargs['list']:
        click.echo(repo.shell_ready_envvars())

@repos.command()
@click.pass_context
def list(ctx):
    session = ctx.obj['session']
    repos = session.query(Repo)
    for repo in repos:
        click.echo(repo.name)


@main.group()
def builds():
    pass


@builds.command()
@click.pass_context
def list(ctx):
    session = ctx.obj['session']
    _builds = session.query(Build).all()
    for build in _builds:
        click.echo(build)


@builds.command()
@click.argument('build_id')
@click.pass_context
def retry(ctx, build_id):
    session = ctx.obj['session']
    build = session.query(Build).filter_by(id=build_id).one()
    if not build:
        click.echo('build not found')
        return

    build.status = Status.created
    session.commit()


if __name__ == '__main__':
    main()
