import logging
import os
import sys

from zeus_ci.config import Config

config = Config()

loglevel = os.getenv('ZEUS_CI_LOGLEVEL') or config.loglevel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if loglevel:
    try:
        level = getattr(logging, loglevel.upper())
        logging.basicConfig(level=level)
        logger.setLevel(level)
        logger.debug('setting loglevel to %s', loglevel.upper())
    except AttributeError:
        logging.error('invalid level specified "%s"', loglevel)
        sys.exit(1)

if not config.loaded:
    logger.debug('config file not found, proceeding without')
