import time
from threading import RLock

import rpyc
from rpyc import ThreadedServer

from zeus_ci import config, logger
from zeus_ci.persistence import Database, User


class BuildThreadRegisterService(rpyc.Service):
    def __init__(self):
        self.lock = RLock()
        self.database = Database(protocol=config.database.get('protocol'),
                                 protocol_args=config.database.get('args'))
        self.containers_allocated = {}  # {username: int(num_containers)}

    def exposed_request_container(self, username):
        with self.lock:
            logger.debug('request for container recieved for: %s', username)
            with self.database.get_session() as session:
                user = session.query(User).filter_by(username=username).one()

                if self.containers_allocated.get(user.username) is None:
                    logger.debug('adding allocation record for currently unrecorded user: %s', username)
                    self.containers_allocated[user.username] = 0

                while self.containers_allocated[user.username] >= user.container_limit:
                    time.sleep(1)
                logger.debug('allocating container for: %s', username)
                self.containers_allocated[user.username] += 1
                return True

    def exposed_return_container(self, username):
        with self.lock:
            logger.debug('container return request recieved for: %s', username)
            with self.database.get_session() as session:
                user = session.query(User).filter_by(username=username).one()

                if self.containers_allocated[user.username] <= 0:
                    self.containers_allocated[user.username] = 0
                else:
                    self.containers_allocated[user.username] -= 1


def main():
    btr = ThreadedServer(BuildThreadRegisterService(), port=config.resource_allocator.get('port', 18861))
    btr.start()


if __name__ == '__main__':
    main()
