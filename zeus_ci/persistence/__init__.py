import logging

from sqlalchemy import Column, Integer, String, JSON, Enum, create_engine, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, backref
from sqlalchemy.orm.attributes import flag_modified

from zeus_ci.runner import Status


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
        return '%s(id: %s, repo: %s, ref: %s, status: %s)' % (
            self.__class__.__name__, self.id, self.repo, self.ref, self.status.name)


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
        self.env_vars.append(var)
        flag_modified(self, 'env_vars')


class User(Base):
    __tablename__ = 'user'

    username = Column(String(50), primary_key=True, nullable=False)
    share_env_vars_with_forks = Column(Boolean(), default=False)
    share_env_vars_with_branches = Column(Boolean(), default=True)
    token = Column(String(50))

    def __repr__(self):
        return '%s(username: %s, token: %s, share_env_with_forks: %s, share_env_with_branches: %s)' % (
            self.__class__.__name__, self.username, self.token,
            self.share_env_vars_with_forks, self.share_env_vars_with_branches
        )


class Database:
    def __init__(self, *_, protocol, protocol_args):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.engine = create_engine('{}:///{}'.format(protocol, protocol_args))
        self.get_session = sessionmaker(bind=self.engine)
        for obj in (Build, Repo, User):
            obj.__table__.create(bind=self.engine, checkfirst=True)

    def __call__(self, *args, **kwargs):
        return self.get_session()
