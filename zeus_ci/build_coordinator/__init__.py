import multiprocessing
import signal
import time

from zeus_ci import runner
from zeus_ci.persistence import SqliteConnection
from zeus_ci.runner import Status


class BuildCoordinator:
    """
    :refs:

    refs/tags/test-tag
    refs/heads/master
    """
    def __init__(self, in_config=None):
        self.config = dict(
            db_filename='/tmp/zeus-ci.db',
            runner_threads=4,
            concurrent_builds=4
        )
        if in_config:
            self.config.update(in_config)

        self.persistence = SqliteConnection(db_filename=self.config['db_filename'])

        self.build_queue = multiprocessing.Queue()
        self.build_pool = multiprocessing.Pool(self.config['concurrent_builds'],
                                               self._run_from_queue, (self.build_queue, ))

    def _run_from_queue(self, queue):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        persistence = SqliteConnection(db_filename=self.config['db_filename'])
        try:
            for build_id in iter(queue.get, None):
                build = persistence.get_builds(build_id=build_id)[0]
                ref = None
                env_vars = []

                if build.ref.startswith('refs/tags/'):
                    ref = build.ref.replace('refs/', '', 1)
                    env_vars.append('ZEUS_TAG={}'.format(ref.replace('refs/tags/', '')))
                    env_vars.append('ZEUS_BRANCH={}'.format(build.json['base_ref'].replace('refs/heads/', '')))
                elif build.ref.startswith('refs/heads/'):
                    ref = build.json['after']
                    env_vars.append('ZEUS_TAG=""')
                    env_vars.append('ZEUS_BRANCH={}'.format(build.ref.replace('refs/heads/', '')))

                if not ref:
                    print('ERROR: {}, refn not detected'.format(build.id))

                else:
                    persistence.update_build(build.id, Status.starting)
                    if runner.main(build.repo, threads=self.config['runner_threads'], ref=ref, env_vars=env_vars):
                        persistence.update_build(build.id, Status.passed)
                    else:
                        persistence.update_build(build.id, Status.failed)
        except Exception as e:
            print('error from process: {}'.format(e))
            persistence.conn.close()



    @property
    def _runnable_builds(self):
        return self.persistence.get_builds([Status.created])

    def run(self):
        try:
            while True:
                if self.build_queue.empty():
                    for build in reversed(self._runnable_builds):
                        self.build_queue.put(build.id)
                time.sleep(1)
        except KeyboardInterrupt:
            print('recieved exit command, closing build processes.')
            for _ in range(self.config['concurrent_builds']):
                self.build_queue.put(None)
            self.build_pool.close()
            self.build_pool.join()
            pass
        print(list(b.status for b in self.persistence.get_builds()))


if __name__ == '__main__':
    builder = BuildCoordinator()
    builder.run()
