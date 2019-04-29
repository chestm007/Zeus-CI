import argparse
import multiprocessing
import signal
import time
import logging

from zeus_ci import runner
from zeus_ci.persistence import Database, Build
from zeus_ci.runner import Status
from zeus_ci.scm_reporter import Github, TokenAuth, GithubStatus


class BuildCoordinator:
    """
    :refs:

    refs/tags/test-tag
    refs/heads/master
    """
    def __init__(self, in_config=None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info('initializing')

        self.database = Database(**in_config.pop('sqlalchemy_args'))

        self.config = dict(
            db_filename='/tmp/zeus-ci.db',
            runner_threads=4,
            concurrent_builds=4
        )

        if in_config:
            self.config.update(in_config)

        self.logger.debug('using config %s', self.config)

        self.build_queue = multiprocessing.Queue()
        self.logger.info('spinning up build process pool')
        self.build_pool = multiprocessing.Pool(self.config['concurrent_builds'],
                                               self._run_from_queue, (self.build_queue, ))

    def _run_from_queue(self, queue):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        session = self.database.get_session()
        try:
            for build_id in iter(queue.get, None):
                build = session.query(Build).filter_by(id=build_id).one()

                # TODO: this must be called as soon as possible due to a race condition with populating the queue
                build.status = Status.starting
                session.commit()
                github = Github(TokenAuth(build.repo.user.token))
                github.update_status(build, GithubStatus.pending)

                try:
                    ref = None
                    env_vars = build.repo.shell_ready_envvars()

                    if build.ref.startswith('refs/tags/'):
                        ref = build.ref.replace('refs/', '', 1)
                        env_vars.append('ZEUS_TAG={}'.format(build.ref.replace('refs/tags/', '')))
                        env_vars.append('ZEUS_BRANCH={}'.format(build.json['base_ref'].replace('refs/heads/', '')))
                    elif build.ref.startswith('refs/heads/'):
                        ref = build.json['after']
                        env_vars.append('ZEUS_TAG=""')
                        env_vars.append('ZEUS_BRANCH={}'.format(build.ref.replace('refs/heads/', '')))

                    if not ref:
                        self.logger.error('error from worker thread: %s, refn not detected', build.id)
                    else:
                        build.status = Status.running
                        session.commit()

                        if runner.main(build.repo.name, threads=self.config['runner_threads'], ref=ref, env_vars=env_vars):
                            github.update_status(build, GithubStatus.success)
                            build.status = Status.passed
                        else:
                            github.update_status(build, GithubStatus.failure)
                            build.status = Status.failed

                        session.commit()
                except Exception as e:
                    github.update_status(build, GithubStatus.error)
                    build.status = Status.error
                    raise e

        except Exception as e:
            self.logger.error('error from worker thread: %s', exc_info=True)
            raise e

        except KeyboardInterrupt:
            pass
        finally:
            session.close()

    @property
    def _runnable_builds(self):
        self.logger.debug('polling database for runnable builds')
        session = self.database.get_session()
        return session.query(Build).filter_by(status=Status.created).all()

    def run(self):
        try:
            self.logger.info('Entering main loop')
            while True:
                if not self.build_queue.empty():
                    continue
                time.sleep(10)

                runnable_builds = self._runnable_builds
                self.logger.debug('runnable_builds: %s', runnable_builds)
                for build in reversed(runnable_builds):
                    self.build_queue.put(build.id)
        except KeyboardInterrupt:
            self.logger.info('recieved exit command, closing build processes.')

        finally:
            for _ in range(self.config['concurrent_builds']):
                self.build_queue.put(None)
            self.build_pool.close()
            self.build_pool.join()
            pass


def main():
    parser = argparse.ArgumentParser(description='Webhook listener for Zeus-CI')
    parser.add_argument('--sqlalchemy-protocol', type=str, default='sqlite')
    parser.add_argument('--sqlalchemy-protocol-args', type=str, default='/tmp/zeus-ci.db')
    parser.add_argument('--runner-threads', type=int)
    parser.add_argument('--concurrent-builds', type=int)
    args = parser.parse_args()
    sqlalchemy_args = dict(
        protocol=args.sqlalchemy_protocol,
        protocol_args=args.sqlalchemy_protocol_args
    )

    config = dict(
        sqlalchemy_args=sqlalchemy_args
    )
    if args.runner_threads:
        logging.debug('setting runner threads to %s', args.runner_threads)
        config['runner_threads'] = args.runner_threads
    if args.concurrent_builds:
        logging.debug('setting concurrent builds to %s', args.concurrent_builds)
        config['concurrent_builds'] = args.concurrent_builds

    builder = BuildCoordinator(config)
    builder.run()


if __name__ == '__main__':
    main()
