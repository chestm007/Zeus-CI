import logging
import os
import sys

loglevel = os.getenv('ZEUS_CI_LOGLEVEL')
logging.basicConfig(level=logging.INFO)

if loglevel:
    try:
        logging.info('setting loglevel to %s', loglevel.upper())
        level = getattr(logging, loglevel.upper())
        logging.basicConfig(level=level)
        logging.root.setLevel(level)  # TODO: find out why this hax is the only fix
        github_logger = logging.getLogger('github.Requester')
        github_logger.setLevel(logging.INFO)
    except AttributeError:
        logging.error('invalid level specified "%s"', loglevel)
        sys.exit(1)
