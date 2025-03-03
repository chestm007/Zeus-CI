from sqlalchemy import Column, Integer, String, JSON, Enum, create_engine, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, backref, Session
from sqlalchemy.orm.attributes import flag_modified

import faust

from zeus_ci import config, Status, logger

Base = declarative_base()


class Build(Base):
    __tablename__ = 'builds'

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_name = Column(String(50), ForeignKey('repo.name'))
    ref = Column(String(50), nullable=False)
    commit = Column(String(50), nullable=False)
    json = Column(JSON(50000))
    status = Column(Enum(Status), nullable=False)

    repo = relationship('Repo', backref=backref('builds'))

    def __repr__(self):
        return '%s(id: %s, repo: %s, ref: %s, commit %s, status: %s)' % (
            self.__class__.__name__, self.id, self.repo, self.ref, self.commit, self.status.name)


class Repo(Base):
    """
    env_vars:
        schema: [{<key>: <value>}, ...]
    """
    __tablename__ = 'repo'

    name = Column(String(50), primary_key=True, nullable=False)
    scm = Column(String(50), nullable=False)
    env_vars = Column(JSON(5000), default=[])
    username = Column(String(50), ForeignKey('user.username'))

    user = relationship('User', backref=backref('repositories'))

    def __repr__(self):
        return '%s(name: %s)' % (self.__class__.__name__, self.name)

    def shell_ready_envvars(self):
        if self.env_vars:
            return ['{}={}'.format(k, v) for var in self.env_vars for k, v in var.items()]
        return []

    def add_envvar(self, var):
        if not self.env_vars:
            self.env_vars = []
        if var in self.env_vars:
            logger.info(f'ENV_VAR:{var} already exists in Repo.')
        self.env_vars.append(var)
        flag_modified(self, 'env_vars')


class User(Base):
    __tablename__ = 'user'

    username = Column(String(50), primary_key=True, nullable=False)
    container_limit = Column(Integer(), default=4)
    share_env_vars_with_forks = Column(Boolean(), default=False)
    share_env_vars_with_branches = Column(Boolean(), default=True)
    token = Column(String(50))

    def __repr__(self):
        return '%s(username: %s, token: %s, share_env_with_forks: %s, share_env_with_branches: %s)' % (
            self.__class__.__name__, self.username, self.token,
            self.share_env_vars_with_forks, self.share_env_vars_with_branches
        )


def _session__enter__(self):
    return self


def _session__exit__(self, *args, **kwargs):
    del args
    del kwargs
    self.commit()
    self.close()


Session.__enter__ = _session__enter__
Session.__exit__ = _session__exit__


class Database:
    def __init__(self, *_, protocol=None, protocol_args=None):
        db_config = config.database
        self.engine = create_engine('{}:///{}'.format(protocol or db_config.get('protocol', 'sqlite'),
                                                      protocol_args or db_config.get('args', '/tmp/zeus-ci.db')))
        self.get_session = sessionmaker(bind=self.engine)
        for obj in (Build, Repo, User):
            obj.__table__.create(bind=self.engine, checkfirst=True)

    def __call__(self, *args, **kwargs):
        return self.get_session()
