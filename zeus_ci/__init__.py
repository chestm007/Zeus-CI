import logging
import os
import sys

loglevel = os.getenv('ZEUS_CI_LOGLEVEL')
logging.basicConfig(level=logging.INFO)

if loglevel:
    try:
        level = getattr(logging, loglevel.upper())
        logging.basicConfig(level=level)
    except AttributeError:
        logging.error('invalid level specified "%s"', loglevel)
        sys.exit(1)
