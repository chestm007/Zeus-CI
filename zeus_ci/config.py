import os

import yaml


class Config:
    file_locations = ['/etc/zeus-ci/']
    filename = 'config.yml'

    def __init__(self):
        self.loaded = False
        self.database: dict = None
        self.listener: dict = None
        self.loglevel: str = None
        self.build_coordinator: dict = None

        self._load_config()

    def _load_config(self) -> None:
        config = None
        for location in self.file_locations:
            try:
                with open(os.path.join(location, 'config.yml'), 'r') as f:
                    config = yaml.safe_load(f)
            except FileNotFoundError:
                continue

        if config:
            self.database = config.get('database', {})
            self.listener = config.get('listener', {})
            self.loglevel = config.get('loglevel', {})
            self.build_coordinator = config.get('build_coordinator', {})
            self.logging = config.get('logging', {})
            self.resource_allocator = config.get('resource_allocator', {})
            self.loaded = True
