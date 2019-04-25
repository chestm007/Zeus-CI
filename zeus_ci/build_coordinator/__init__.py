import multiprocessing
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
        persistence = SqliteConnection(db_filename=self.config['db_filename'])
        for build_id in iter(queue.get, None):
            build = persistence.get_builds(build_id=build_id)[0]
            ref = None

            if build.ref.startswith('refs/tags'):
                ref = build.ref.replace('refs/', '', 1)
            elif build.ref.startswith('refs/heads'):
                ref = build.json['after']

            if not ref:
                print('err')
            else:
                print(build)
                persistence.update_build(build.id, Status.starting)
                if runner.main(build.repo, threads=self.config['runner_threads'], ref=ref):
                    persistence.update_build(build.id, Status.passed)
                else:
                    persistence.update_build(build.id, Status.failed)



    @property
    def _runnable_builds(self):
        return self.persistence.get_builds([Status.created])

    def run(self):
        try:
            while True:
                for build in reversed(self._runnable_builds):
                    self.build_queue.put(build.id)
                time.sleep(10)
        except KeyboardInterrupt:
            for _ in range(self.config['concurrent_builds']):
                self.build_queue.put(None)
            self.build_pool.close()
            self.build_pool.join()
            pass
        print(list(b.status for b in self.persistence.get_builds()))


if __name__ == '__main__':
    builder = BuildCoordinator()
    builder.run()
