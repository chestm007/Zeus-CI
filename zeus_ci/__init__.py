import logging
import os
import sys
from enum import Enum

from zeus_ci.config import Config

config = Config()

Status = Enum('status', 'created starting running passed failed skipped error')

status_from_name_mapping = {s.name: s for s in Status}
status_from_value_mapping = {s.value: s for s in Status}


def status_from_name(name_):
    return status_from_name_mapping[name_]


def status_from_value(value_):
    return status_from_value_mapping[value_]



logger = logging.getLogger(__name__)
loglevel = os.getenv('ZEUS_CI_LOGLEVEL') or config.logging.get('level', 'info')
logformat = config.logging.get('format', '%(asctime)s: %(name)s: %(threadName)s: %(message)s')

try:
    level = getattr(logging, loglevel.upper())
except AttributeError:
    logging.error('invalid level specified "%s"', loglevel)
    sys.exit(1)

logging_config = dict(
    level=level,
    format=logformat
)

logpath = config.logging.get('filepath')
if logpath:
    fh = logging.FileHandler(logpath)
    fh.setLevel(logging_config['level'])
    logger.addHandler(fh)

if config.logging.get('use_journald'):
    from systemd.journal import JournalHandler

    logger.addHandler(JournalHandler())

logging.basicConfig(**logging_config)
logger.setLevel(level)
logger.debug('setting loglevel to %s', loglevel.upper())

if not config.loaded:
    logger.debug('config file not found, proceeding without')
