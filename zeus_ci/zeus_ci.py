import argparse
import os
import shutil
import subprocess
import sys
import time
from enum import Enum
from multiprocessing.pool import ThreadPool
from subprocess import PIPE
from typing import Dict, List

import yaml
import uuid


Status = Enum('status', 'created starting running passed failed skipped')


class ProcessOutput:
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
        return '==stdout==\n{}\n\n\n==stderr==\n{}\n'.format(self.stdout, self.stderr)

    def __repr__(self):
        return '{}(stdout={}, stderr={}, returncode={})'.format(
            self.__class__.__name__, self.stdout, self.stderr, self.returncode)


def _exec(cmd: list) -> ProcessOutput:
    proc = subprocess.Popen(cmd, stderr=PIPE, stdout=PIPE)
    stdout, stderr = proc.communicate()
    process_output = ProcessOutput(stdout, stderr, proc.returncode)
    return process_output


class DockerContainer:
    workspace_dir = '/tmp/zeus-ci'

    def __init__(self, name: str, image: str, exec_uuid: uuid, clone_url: str, working_directory: str = None,
                 env_vars: List[str] = None):
        self._start_time = time.time()
        self._duration = None
        self.failed = False
        self.passed = False

        self.clone_url = clone_url
        self.image = str(image)
        self.name = str(name)
        self.exec_uuid = exec_uuid
        self.env_vars = env_vars or []

        self.env_vars.append('CIRCLE_JOB={}'.format(self.name))
        self._stop()
        self._start()
        self.w_dir = None
        if working_directory and working_directory.startswith('~'):
            tilda = self.exec('echo $HOME').stdout.strip('\n')
            working_directory = working_directory.replace('~', tilda)
            self.exec('mkdir {}'.format(working_directory))
            self.w_dir = working_directory

    def _start(self) -> ProcessOutput:
        info = _exec(['docker', 'run', '--detach', '-ti', '--name', self.name, self.image])
        return info

    def _stop(self) -> ProcessOutput:
        info = _exec(['docker', 'rm', '-f', self.name])
        return info

    def exec(self, command: str) -> ProcessOutput:
        cmd = ['docker', 'exec']
        if self.w_dir is not None:
            cmd.extend(['-w', self.w_dir])
        for env in self.env_vars:
            cmd.extend(['-e', env])
        cmd.append(self.name)
        cmd.extend(['bash', '-c', command])
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
        print('persist to workspace failed: {}'.format(info))

    def copy_workspace_to_container(self, dest: str) -> bool:
        self.exec('mkdir -p {}'.format(dest))
        current_workspace_path = '{}/{}'.format(self.workspace_dir, self.exec_uuid)
        for file in os.listdir(current_workspace_path):
            file_path = os.path.join(self.workspace_dir, self.exec_uuid, file)
            info = _exec(['docker', 'cp', file_path, '{}:{}'.format(self.name, dest)])
            if not info:
                print('attach workspace failed: {}'.format(info))
                return False
        return True

    @property
    def duration(self) -> float:
        if self._duration is not None:
            return self._duration
        return time.time() - self._start_time

    def stop(self) -> None:
        self._stop()
        self._duration = time.time() - self._start_time


class Stage:
    def __init__(self, name: str, exec_uuid: uuid, clone_url: str, spec: Dict[str, dict], env_vars: List[str] = None,
                 requires: str = None):
        self.name = name
        self.requires = requires
        self.state = Status.created

        self.exec_uuid = exec_uuid
        self.clone_url = clone_url
        self.env_vars = env_vars
        self.steps = spec.get('steps')
        self.working_directory = spec.get('working_directory')
        self.docker = DockerContainer(self.name, spec.get('docker')[0].get('image'), self.exec_uuid,
                                      self.clone_url, self.working_directory, self.env_vars)
        self.steps = [Step.factory(self.docker, step) for step in spec.get('steps')]

    def run(self) -> None:
        self.state = Status.running
        print('---- Running Job: {} ----'.format(self.name))
        for step in self.steps:
            print('Executing Step: {}'.format(str(step)))
            output = step.run()
            if not output:
                print('ERROR: Job[{}]\n{}'.format(self.name, output.output))
                self.state = Status.failed
                return
        print('Job ({}) Passed in {:.2f} seconds'.format(self.name, self.docker.duration))
        self.state = Status.passed


class Step:
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
        raise NotImplementedError('FUCKED {}'.format(step))

    def run(self) -> ProcessOutput:
        raise NotImplementedError()


class PersistStep(Step):
    def init(self, spec: dict) -> None:
        self.root = spec.get('root')
        self.paths = spec.get('paths')

    def run(self) -> bool:
        out = self.docker.persist_to_tmp(self.root, self.paths)
        return out

    def __str__(self):
        return 'persist_to_workspace: root({}) paths({})'.format(self.root, self.paths)


class AttachStep(Step):
    def init(self, spec: dict) -> None:
        self.at = spec.get('at')

    def run(self) -> bool:
        out = self.docker.copy_workspace_to_container(self.at)
        return out

    def __str__(self):
        return 'attach_workspace: {}'.format(self.at)


class CheckoutStep(Step):
    def run(self) -> ProcessOutput:
        out = self.docker.exec('git clone {} .'.format(self.docker.clone_url))
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
    try:
        os.mkdir(DockerContainer.workspace_dir)
    except FileExistsError:
        pass


class Workflow:
    def __init__(self, name: int,
                 jobs: Dict[str, dict],
                 spec: Dict[str, dict],
                 clone_url: str,
                 num_threads: int,
                 env_vars: List[str] = None):

        self.exec_uuid = uuid.uuid4().hex
        self.status = Status.created
        self.num_threads = num_threads
        self.name = name
        os.mkdir('{}/{}'.format(DockerContainer.workspace_dir, self.exec_uuid))

        self.stages = {}
        for name in spec['stages']:
            requires = None
            if type(name) == dict:
                requires = list(name.values())[0].get('requires')
                name = list(name.keys())[0]
            self._add_stage(Stage(name, self.exec_uuid, clone_url, jobs.get(name),
                                  requires=requires, env_vars=env_vars))
        self._populate_requires()

    def _populate_requires(self) -> None:
        for stage in self.stages.values():
            if stage.requires and all(type(r) == str for r in stage.requires):
                stage.requires = [self.stages[r] for r in stage.requires]

    def _runnable_stages(self) -> List[Stage]:
        if not any(s.state in (Status.created, Status.starting, Status.running) for s in self.stages.values()):
            print([[s.name, s.state] for s in self.stages.values()])
            raise StopIteration
        for stage in self.stages.values():
            if stage.state == Status.created:
                if stage.requires:
                    if all(r.state == Status.passed for r in stage.requires):
                        yield stage
                    elif any(r.state in (Status.failed, Status.skipped) for r in stage.requires):
                        print('skipping {}'.format(stage.name))
                        stage.state = Status.skipped
                else:
                    yield stage
        print('spinning')
        time.sleep(1)

    def _add_stage(self, stage: Stage) -> None:
        self.stages[stage.name] = stage

    def run(self) -> None:
        self.status = Status.running
        pool = ThreadPool(self.num_threads)
        results = pool.map(self._run_stage, self._runnable_stages)

        print(self.status_string)

    @staticmethod
    def _run_stage(stage: Stage) -> bool:
        """
        runs the Stage passed in
        returns True if Stage passed, or False if it  fails
        """
        stage.state = Status.starting
        stage.run()
        if stage.state == Status.passed:
            return True
        return False

    @property
    def status_string(self) -> str:
        format_string = "{num_stages} {state}\n{stage_summary}\n\n"

        status_string = ''
        for state in (Status.failed, Status.passed, Status.skipped):
            stages = set(filter(lambda s: s.state == state, self.stages.values()))
            if stages:
                status_string += format_string.format(num_stages=len(stages),
                                                      state=state.name,
                                                      stage_summary='\n'.join(s.name for s in stages))
        return status_string


def main(repo_slab: str = None, env_vars: List[str] = None, clean: bool = True, threads: int = 1) -> bool:
    parser = argparse.ArgumentParser(description='Run Zeus-CI jobs locally through docker')
    parser.add_argument('--env', type=str, nargs='+', help='K=V environment vars to pass to the test')
    parser.add_argument('--clean', type=bool,
                        help='dont remove {} files or docker containers'.format(DockerContainer.workspace_dir))
    parser.add_argument('--threads', type=int, help='number of worker threads(docker containers) to run concurrently')
    args = parser.parse_args()

    if args.threads:
        threads = args.threads

    env_vars = env_vars.extend(args.env) if env_vars else args.env
    if args.clean:
        clean = args.clean

    if not repo_slab:
        repo_slab = None
        # This is insanely nasty and likely fragile as fuck - it takes a list of gir remotes and decodes
        # the github slab (chestm007/Zeus-CI) from it. supports git and http as of now, but will likely
        # support most other types.

        def get_slab(in_):
            return '/'.join(in_.split(':')[-1].replace('.git', '').split('/')[-2:])

        for line in _exec(['git', 'remote', '-v']).stdout.splitlines():
            if '(fetch)' in line:
                repo_slab = get_slab(line.split()[1])

        if not repo_slab:
            print('not in the root directory of a git repository, exiting')
            sys.exit(1)

    _setup()

    clone_url = 'https://github.com/{}.git'.format(repo_slab)
    _verify_deps_exist()
    config = _load_circle_config()
    workflow_version = config.get('workflows').pop('version')

    workflows = {name: Workflow(name, config['jobs'], spec, clone_url, threads, env_vars=env_vars)
                 for name, spec in config['workflows'].items()}

    for workflow_name, workflow in workflows.items():
        workflow.run()

        for stage_name, stage in workflow.stages.items():
            if clean:
                stage.docker.stop()

        if not clean:
            return True
        shutil.rmtree('{}/{}'.format(DockerContainer.workspace_dir, workflow.exec_uuid))


def _load_circle_config() -> dict:
    with open('.zeusci/config.yml') as f:
        config = yaml.load(f, yaml.Loader)
    return config


def _verify_deps_exist() -> None:
    for binary in ('docker', 'git'):
        try:
            _exec([binary])
        except FileNotFoundError:
            print('{} not installed'.format(binary))


if __name__ == '__main__':
    main()
