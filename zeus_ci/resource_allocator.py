from multiprocessing import Manager
from threading import RLock

import rpyc
from rpyc import ThreadedServer

from zeus_ci import config, logger
from zeus_ci.persistence import Database, User


class BuildThreadRegisterService(rpyc.Service):
    def __init__(self):
        self.write_lock = RLock()
        self.read_lock = RLock()
        self.database = Database(protocol=config.database.get('protocol'),
                                 protocol_args=config.database.get('args'))
        self.manager = Manager()
        self.containers_allocated = self.manager.dict()  # {username: int(num_containers)}

    def exposed_request_container(self, username):
        logger.debug('request for container recieved for: %s', username)
        with self.database.get_session() as session:
            user = session.query(User).filter_by(username=username).one()

            with self.read_lock:
                if self.containers_allocated.get(user.username) is None:
                    logger.debug('adding allocation record for currently unrecorded user: %s', username)
                    with self.write_lock:
                        self.containers_allocated[user.username] = 0

            with self.read_lock:
                if self.containers_allocated[user.username] >= user.container_limit:
                    return False
                else:
                    logger.debug('allocating container for: %s', username)
                    with self.write_lock:
                        self.containers_allocated[user.username] += 1
                    return True

    def exposed_return_container(self, username):
        logger.debug('container return request recieved for: %s', username)
        with self.database.get_session() as session:
            user = session.query(User).filter_by(username=username).one()

            if self.containers_allocated[user.username] <= 0:
                with self.write_lock:
                    self.containers_allocated[user.username] = 0
            else:
                with self.write_lock:
                    self.containers_allocated[user.username] -= 1
            logger.debug('container return request processed for: %s', user.username)


def main():
    btr = ThreadedServer(BuildThreadRegisterService(), port=config.resource_allocator.get('port', 18861))
    btr.start()


if __name__ == '__main__':
    main()
