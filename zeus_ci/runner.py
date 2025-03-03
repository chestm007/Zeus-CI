import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
from multiprocessing.pool import ThreadPool, ApplyResult
from subprocess import PIPE
from typing import Dict, List

import rpyc
import yaml
import uuid

from zeus_ci import logger, config, Status


class Stateful:
    """
    this entire class is a python anti-pattern, i know - its not java i promise. I got fed up
    with confusing state and status
    """
    def __init__(self):
        self.state = Status.created


class ProcessOutput:
    """
    Represents output from a process

    Evaluates to True if process returncode == 0, False otherwise
    """
    def __init__(self, stdout: bytes, stderr: bytes, returncode: int):
        self.stdout = stdout.decode()
        self.stderr = stderr.decode()
        self.returncode = returncode

    def __nonzero__(self):
        return self.__bool__()

    def __bool__(self):
        if self.returncode == 0:
            return True
        return False

    @property
    def output(self):
        return f'==stdout==\n{self.stdout}\n\n\n==stderr==\n{self.stderr}\n'

    def __repr__(self):
        return f'{self.__class__.__name__}(returncode={self.returncode})'


def _exec(cmd: list) -> ProcessOutput:
    proc = subprocess.Popen(cmd, stderr=PIPE, stdout=PIPE)
    stdout, stderr = proc.communicate()
    process_output = ProcessOutput(stdout, stderr, proc.returncode)
    return process_output


class DockerContainer:
    workspace_dir = '/tmp/zeus-ci'

    def __init__(self,
                 name: str,
                 image: str,
                 exec_uuid: uuid,
                 clone_url: str,
                 working_directory: str = None,
                 env_vars: List[str] = None,
                 ref: str = None):

        self._start_time = time.time()
        self._duration = None
        self.failed = False
        self.passed = False

        self.clone_url = clone_url
        self.image = str(image)
        self._working_directory = working_directory
        self.exec_uuid = exec_uuid
        self.name = '{}-{}'.format(str(name), self.exec_uuid)
        self.stage_name = str(name)
        self.env_vars = env_vars or []
        for env_var in self.env_vars:
            if env_var.startswith('ZEUS_USERNAME='):
                self.username = env_var.split('ZEUS_USERNAME=')[-1]
        self.ref = ref

        self.resource_allocator = rpyc.connect(config.resource_allocator.get('address', 'localhost'),
                                               config.resource_allocator.get('port', 18861))

        self.env_vars.append('ZEUS_JOB={}'.format(self.stage_name))
        self.w_dir = None

    def __enter__(self):
        self.start()
        return self

    def start(self) -> ProcessOutput:
        logger.debug('waiting for free docker container allocation')

        while True:
            if self.resource_allocator.root.request_container(self.username):
                break
            time.sleep(1)

        logger.debug('got "good to go" from resource allocator')

        info = _exec(['docker', 'run', '--detach', '-ti', '--name', self.name, self.image])
        if self._working_directory and self._working_directory.startswith('~'):
            tilda = self.exec('echo $HOME').stdout.strip('\n')
            working_directory = self._working_directory.replace('~', tilda)
            self.exec('mkdir {}'.format(working_directory))
            self.w_dir = working_directory
        return info

    def exec(self, command: str) -> ProcessOutput:
        cmd = ['docker', 'exec']
        if self.w_dir is not None:
            cmd.extend(['-w', self.w_dir])
        for env in self.env_vars:
            cmd.extend(['-e', env])
        cmd.append(self.name)
        cmd.extend(['sh', '-c', command])
        out = _exec(cmd)
        return out

    def persist_to_tmp(self, root: str, paths: str) -> bool:
        files = self.exec('cd {} && echo `pwd`/`ls -d {}`'.format(root, paths)).stdout.splitlines()
        for file in files:
            if not self._copy_file_to_workspace(file):
                return False
        return True

    def _copy_file_to_workspace(self, src: str) -> bool:
        info = _exec(['docker', 'cp',
                      '{}:{}'.format(self.name, src),
                      '{}/{}'.format(self.workspace_dir, self.exec_uuid)])
        if info.returncode == 0:
            return True
        logger.error('persist to workspace failed: %s', info)

    def copy_workspace_to_container(self, dest: str) -> bool:
        self.exec('mkdir -p {}'.format(dest))
        current_workspace_path = '{}/{}'.format(self.workspace_dir, self.exec_uuid)
        for file in os.listdir(current_workspace_path):
            file_path = os.path.join(self.workspace_dir, self.exec_uuid, file)
            info = _exec(['docker', 'cp', file_path, '{}:{}'.format(self.name, dest)])
            if not info:
                logger.error('attach workspace failed: %s', info)
                return False
        return True

    @property
    def duration(self) -> float:
        if self._duration is not None:
            return self._duration
        return time.time() - self._start_time

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def _stop(self) -> ProcessOutput:
        self.resource_allocator.root.return_container(self.username)
        return _exec(['docker', 'rm', '-f', self.name])

    def stop(self) -> ProcessOutput:
        info = self._stop()
        self._duration = time.time() - self._start_time
        return info


class Stage(Stateful):
    def __init__(self,
                 name: str,
                 exec_uuid: uuid,
                 clone_url: str,
                 spec: Dict[str, dict],
                 env_vars: List[str] = None,
                 requires: str = None,
                 ref: str = None,
                 run_condition: dict = None):

        super().__init__()

        self.name = name
        self.requires = requires
        self.stderr = ''
        self.stdout = ''
        self.ref = ref
        self.tag = None
        self.branch = None

        if not env_vars:
            env_vars = []
        self.env_vars = list(env_vars)
        self.env_vars.append('ZEUS_JOB={}'.format(self.name))
        for env_var in self.env_vars:
            if env_var.startswith('ZEUS_TAG='):
                self.tag = env_var.split('ZEUS_TAG=', 1)[-1]
            elif env_var.startswith('ZEUS_BRANCH='):
                self.branch = env_var.split('ZEUS_BRANCH=', 1)[-1]

        self.run_condition = run_condition or {}

        self.exec_uuid = exec_uuid
        self.clone_url = clone_url
        self.spec = spec
        self.working_directory = spec.get('working_directory')

    def run(self) -> None:

        logger.debug(f'_run_stage() called for {self.name}')
        with DockerContainer(self.name, self.spec.get('docker')[0].get('image'), self.exec_uuid,
                             self.clone_url, self.working_directory, self.env_vars, ref=self.ref) as docker:

            self.steps = [Step.factory(docker, step) for step in self.spec.get('steps')]
            skip = False
            if self.run_condition.get('branch'):
                if not re.search(self.run_condition['branch'], self.branch):
                    logger.debug('skipping %s because %s doesnt match condition %s',
                                 self.name, self.branch, self.run_condition['branch'])
                    self.state = Status.skipped
                    skip = True
            if self.run_condition.get('tag'):
                if not re.search(self.run_condition['tag'], self.tag):
                    logger.debug('skipping %s because %s doesnt match condition %s',
                                 self.name, self.tag, self.run_condition['tag'])
                    self.state = Status.skipped
                    skip = True

            if not skip:
                self.state = Status.running
                try:
                    logger.info('---- Running Job: %s ----', self.name)
                    logger.debug('exec_uuid: %s, env_vars: %s', self.exec_uuid, self.env_vars)
                    for step in self.steps:
                        logger.info('Executing Step: %s', step)
                        output = step.run()

                        # TODO: log step names - currently they dont know their own name
                        self.stdout += output.stdout
                        self.stderr += output.stderr
                        if not output:
                            logger.error(f'Job Failed[{self.name}]')
                            self.state = Status.failed
                            return self.state

                    logger.info('Job (%s) Passed in %.2f seconds', self.name, docker.duration)
                except Exception as e:
                    self.state = Status.failed
                    raise e
                self.state = Status.passed
            return self.state


class Step:
    name = 'step'

    def __init__(self, docker: DockerContainer, *args):
        self.docker = docker
        self.init(*args)

    def init(self, *args) -> None:
        pass

    @classmethod
    def factory(cls, docker: DockerContainer, step=None) -> 'Step':
        if step == 'checkout':
            return CheckoutStep(docker)
        elif step.get('run'):
            return RunStep(docker, step.get('run'))
        elif step.get('persist_to_workspace'):
            return PersistStep(docker, step.get('persist_to_workspace'))
        elif step.get('attach_workspace'):
            return AttachStep(docker, step.get('attach_workspace'))
        else:
            raise NotImplementedError()

    def run(self) -> ProcessOutput:
        raise NotImplementedError()


class PersistStep(Step):
    name = 'persist'
    def init(self, spec: dict) -> None:
        self.root = spec.get('root')
        self.paths = spec.get('paths')

    def run(self) -> bool:
        out = self.docker.persist_to_tmp(self.root, self.paths)
        return out

    def __str__(self):
        return 'persist_to_workspace: root({}) paths({})'.format(self.root, self.paths)


class AttachStep(Step):
    name = 'attach'
    def init(self, spec: dict) -> None:
        self.at = spec.get('at')

    def run(self) -> bool:
        out = self.docker.copy_workspace_to_container(self.at)
        return out

    def __str__(self):
        return 'attach_workspace: {}'.format(self.at)


class CheckoutStep(Step):
    name = 'checkout'
    def run(self) -> ProcessOutput:
        out = self.docker.exec(f'git clone {self.docker.clone_url} .')

        if not self.docker.ref:  # if we arent building a tag/commit, just return
            logger.debug(f'git clone {self.docker.clone_url}')
            return out

        out = self.docker.exec(f'git checkout {self.docker.ref}')
        logger.debug(f'git checkout {self.docker.ref}')
        return out

    def __str__(self):
        return 'checkout'


class RunStep(Step):
    def init(self, spec: dict) -> None:
        self.name = spec.get('name')
        self.command = spec.get('command')

    def run(self) -> ProcessOutput:
        out = self.docker.exec(self.command)
        return out

    def __str__(self):
        return '{}\n{}'.format(self.name or '', self.command)


def _setup() -> None:
    for binary in ('docker', 'git'):
        try:
            _exec([binary])
        except FileNotFoundError:
            logger.error('%s not installed', binary)

    try:
        os.mkdir(DockerContainer.workspace_dir)
    except FileExistsError:
        logger.info('workspace directory already exists at %s - this '
                    'is harmless providing it\'s what you wanted', DockerContainer.workspace_dir)
        pass


class Workflow(Stateful):
    def __init__(self, name: int,
                 build_id: int,
                 stages: Dict[str, dict],
                 spec: Dict[str, dict],
                 clone_url: str,
                 num_threads: int,
                 env_vars: List[str] = None,
                 ref: str = None):

        super().__init__()

        self.exec_uuid = uuid.uuid4().hex
        self.build_id = build_id
        self.num_threads = num_threads
        self.name = name
        self.ref = ref
        os.mkdir('{}/{}'.format(DockerContainer.workspace_dir, self.exec_uuid))

        self.stages = {}
        for stage in spec['stages']:

            try:
                stage_name = list(stage.keys())[0]
                requires = stage[stage_name].get('requires')
                run_condition = stage[stage_name].get('run_when')
            except AttributeError:
                stage_name = stage
                requires = None
                run_condition = None

            self._add_stage(
                Stage(stage_name,
                      self.exec_uuid,
                      clone_url,
                      stages.get(stage_name),
                      requires=requires,
                      env_vars=env_vars,
                      ref=self.ref,
                      run_condition=run_condition))

        self._populate_requires()

    def _populate_requires(self) -> None:
        for stage in self.stages.values():
            if stage.requires and all(type(r) == str for r in stage.requires):
                stage.requires = [self.stages[r] for r in stage.requires]

    def runnable_stages(self) -> List[Stage]:
        runnable_stages = []
        if not any(s.state in (Status.created, Status.starting, Status.running) for s in self.stages.values()):
            raise StopIteration
        for stage in self.stages.values():
            if stage.state == Status.created:
                if stage.requires:
                    if all(r.state == Status.passed for r in stage.requires):
                        runnable_stages.append(stage)
                    elif any(r.state in (Status.failed, Status.skipped) for r in stage.requires):
                        logger.info('skipping %s', stage.name)
                        stage.state = Status.skipped
                else:
                    runnable_stages.append(stage)

        return runnable_stages

    def _add_stage(self, stage: Stage) -> None:
        self.stages[stage.name] = stage

    def run(self) -> None:
        logger.debug(f'Workflow.run() for {self.build_id}/{self.name}')
        self.state = Status.running
        pool = ThreadPool(self.num_threads)
        pool_results: list[ApplyResult] = []

        while True:
            try:
                stages = self.runnable_stages()
                if stages:
                    for stage in stages:
                        logger.debug(f'adding stage: {stage.name} to workflow {self.name}:{self.exec_uuid}')
                        stage.state = Status.starting
                        pool_results.append(pool.apply_async(self._run_stage, (stage, )))
                time.sleep(1)
            except StopIteration:
                break
        pool.close()
        pool.join()
        results = [r.get() for r in pool_results]
        for r in results:
            self._log_to_file(r)

        logger.info(self.status_string)

        for status in (Status.error, Status.failed):
            if any(map(lambda r: r.state == status, results)):
                return status

        return Status.passed

    def _log_to_file(self, stage):
        build_log_location = '/etc/zeus-ci/builds'
        try:
            logger.debug(f'creating log location at: {build_log_location}')
            os.mkdir(build_log_location)
        except FileExistsError:
            logger.debug('folder already exists, skipping')
            pass

        this_build_log_location = f'{build_log_location}/{self.build_id}'
        try:
            logger.debug(f'creating build directory at: {this_build_log_location}')
            os.mkdir(this_build_log_location)
        except FileExistsError:
            logger.debug(f'folder already exists, skipping')
            pass

        with open(f'{this_build_log_location}/{self.name}', 'a') as logfile:
            logfile.write(f'STDOUT:\n{stage.stdout}\n\nSTDERR:\n{stage.stderr}\n\n')

    @staticmethod
    def _run_stage(stage: Stage) -> Stage:
        """
        runs the Stage passed in
        returns True if Stage passed, or False if it  fails
        """
        stage.state = Status.running
        stage.run()
        return stage

    @property
    def status_string(self) -> str:

        statuses = []
        for state in (Status.failed, Status.passed, Status.skipped):
            stages = set(filter(lambda s: s.state == state, self.stages.values()))
            if stages:
                statuses.append(f'{len(stages)} {state.name} [{", ".join(s.name for s in stages)}]')

        return ' || '.join(statuses)


def main(repo_slab: str,
         build_id: int,
         env_vars: List[str] = None,
         threads: int = 1,
         ref=None) -> bool:

    # TODO: im not sure if this logic is even used
    if not any([repo_slab, env_vars, threads, ref]):

        if not repo_slab:
            repo_slab = repo_slab_of_cwd()

            if not repo_slab:
                logger.error('not in the root directory of a git repository, exiting')
                sys.exit(1)

    _setup()

    clone_url = 'https://github.com/{}.git'.format(repo_slab)
    _config = _download_repo_build_config(repo_slab, ref)
    if not config:
        return False

    try:
        _config['workflows'].pop('version')
    except KeyError:
        pass

    env_vars.append('ZEUS_USERNAME={}'.format(repo_slab.split('/')[0]))

    workflows = {name: Workflow(name, build_id, _config['jobs'], spec, clone_url, threads, env_vars=env_vars, ref=ref)
                 for name, spec in _config['workflows'].items()}

    results = []
    for workflow_name, workflow in workflows.items():
        try:
            results.append(workflow.run())
        except Exception as e:
            logger.error('%s: %s', workflow_name, e)

    for status in (Status.error, Status.failed):
        if any(map(lambda r: r == status, results)):
            return status

    return Status.passed


def repo_slab_of_cwd():
    # This is insanely nasty and likely fragile as fuck - it takes a list of gir remotes and decodes
    # the github slab (chestm007/Zeus-CI) from it. supports git and http as of now, but will likely
    # support most other types.
    for line in _exec(['git', 'remote', '-v']).stdout.splitlines():
        if '(fetch)' in line:
            remote_url = line.split(';')[-1]   # remove ssh specific part of url
            remote_url = '/'.join(remote_url.split('/')[-2:])  # remote https specific part of url
            remote_url = remote_url.strip('.git')
            return remote_url.split(' ')[0]


def _download_repo_build_config(repo_slab, ref) -> dict:
    """
    last commit to master:
    https://raw.githubusercontent.com/chestm007/Zeus-CI/master/.zeusci/config.yml

    specific commit:
    https://raw.githubusercontent.com/chestm007/Zeus-CI/142eb4bdbbc54371cbcc4a0000bd8eeea997d1f2/.zeusci/config.yml

    specific tag:
    https://raw.githubusercontent.com/chestm007/Zeus-CI/test-tag/.zeusci/config.yml
    """
    url_format = 'https://raw.githubusercontent.com/{repo_slab}/{ref}/.zeusci/config.yml'
    try:
        response = urllib.request.urlopen(url_format.format(repo_slab=repo_slab, ref=ref.split('/')[-1]))
    except urllib.error.HTTPError:
        logger.error('couldnt fetch build config')
        return {}

    if response.status == 200:
        _config = yaml.load(response, yaml.Loader)
        return _config
