import argparse
import multiprocessing
import signal
import time

from zeus_ci import runner, logger, Status, Config
from zeus_ci.persistence import Database, Build
from zeus_ci.scm_reporter import Github, TokenAuth, GithubStatus


class BuildCoordinator:
    """
    :refs:

    refs/tags/test-tag
    refs/heads/master
    """
    def __init__(self, in_config=None):
        logger.info('initializing')

        self.database = Database(**in_config.pop('sqlalchemy_args'))

        self.config = dict(
            db_filename='/tmp/zeus-ci.db',
            runner_threads=4,
            concurrent_builds=4
        )

        if in_config:
            self.config.update(in_config)

        logger.debug('using config %s', self.config)

        self.build_queue = multiprocessing.Queue()
        logger.info('spinning up build process pool')
        self.build_pool = multiprocessing.Pool(self.config['concurrent_builds'],
                                               self._run_from_queue, (self.build_queue, ))

    def _run_from_queue(self, queue):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        with self.database.get_session() as session:
            try:
                for build_id in iter(queue.get, None):
                    build = session.query(Build).filter_by(id=build_id).one()

                    # TODO: this must be called as soon as possible due to a race condition with populating the queue
                    build.status = Status.starting
                    session.commit()
                    github = Github(TokenAuth(build.repo.user.token))
                    logger.debug(f'building github object for user: {build.repo.user}')
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
                            logger.error('error from worker thread: %s, refn not detected', build.id)
                        else:
                            build.status = Status.running
                            session.commit()

                            logger.debug('executing runner.main process')
                            status = runner.main(
                                build.repo.name,
                                threads=self.config['runner_threads'],
                                ref=ref,
                                env_vars=env_vars)
                            logger.debug("runner main process completed")

                            if status == Status.passed:
                                logger.debug("build passed")
                                github.update_status(build, GithubStatus.success)
                                build.status = Status.passed
                            else:
                                logger.debug("build failed")
                                github.update_status(build, GithubStatus.failure)
                                build.status = Status.failed

                            session.commit()
                    except Exception as e:
                        github.update_status(build, GithubStatus.error)
                        build.status = Status.error
                        raise e

            except Exception as e:
                logger.error('error from worker thread: %s', exc_info=True)
                raise e

            except KeyboardInterrupt:
                pass

    def _runnable_builds(self, session):
        return session.query(Build).filter_by(status=Status.created).all()

    def run(self):
        try:
            with self.database.get_session() as session:
                logger.info('Entering main loop')
                while True:
                    if not self.build_queue.empty():
                        continue
                    time.sleep(self.config['build_poll_sec'])

                    runnable_builds = self._runnable_builds(session)
                    if runnable_builds:
                        logger.debug('runnable_builds: %s', runnable_builds)
                    for build in reversed(runnable_builds):
                        self.build_queue.put(build.id)
        except KeyboardInterrupt:
            logger.info('recieved exit command, closing build processes.')

        finally:
            for _ in range(self.config['concurrent_builds']):
                self.build_queue.put(None)
            self.build_pool.close()
            self.build_pool.join()
            pass


def main():
    parser = argparse.ArgumentParser(description='Webhook listener for Zeus-CI')
    parser.add_argument('--sqlalchemy-protocol', type=str)
    parser.add_argument('--sqlalchemy-protocol-args', type=str)
    parser.add_argument('--runner-threads', type=int)
    parser.add_argument('--concurrent-builds', type=int)
    parser.add_argument('--build-poll-sec', type=int, help='interval between database polling for new builds',
                        default=10)
    args = parser.parse_args()

    loaded_config = Config()
    sqlalchemy_args = dict(
        protocol=args.sqlalchemy_protocol or loaded_config.database.get('protocol'),
        protocol_args=args.sqlalchemy_protocol_args or loaded_config.database.get('args')
    )

    config = dict(
        sqlalchemy_args=sqlalchemy_args,
        build_poll_sec=args.build_poll_sec
    )

    logger.info(f'Using config: {config}')

    if args.runner_threads:
        logger.debug('setting runner threads to %s', args.runner_threads)
        config['runner_threads'] = args.runner_threads
    if args.concurrent_builds:
        logger.debug('setting concurrent builds to %s', args.concurrent_builds)
        config['concurrent_builds'] = args.concurrent_builds

    builder = BuildCoordinator(config)
    builder.run()


if __name__ == '__main__':
    main()
