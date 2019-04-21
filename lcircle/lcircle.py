import argparse
import os
import shutil
import subprocess
import sys
import time
from enum import Enum
from subprocess import PIPE

import yaml
import uuid


class ProcessOutput:
    def __init__(self, stdout, stderr, returncode):
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


Status = Enum('status', 'created running passed failed')


def _exec(cmd):
    proc = subprocess.Popen(cmd, stderr=PIPE, stdout=PIPE)
    stdout, stderr = proc.communicate()
    process_output = ProcessOutput(stdout, stderr, proc.returncode)
    return process_output


class DockerContainer:
    def __init__(self, name, image, exec_uuid, clone_url, working_directory=None, env_vars=None):
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

    def _start(self):
        info = _exec(['docker', 'run', '--detach', '-ti', '--name', self.name, self.image])
        return info

    def _stop(self):
        info = _exec(['docker', 'rm', '-f', self.name])
        return info

    def exec(self, command):
        cmd = ['docker', 'exec']
        if self.w_dir is not None:
            cmd.extend(['-w', self.w_dir])
        for env in self.env_vars:
            cmd.extend(['-e', env])
        cmd.append(self.name)
        cmd.extend(['bash', '-c', command])
        out = _exec(cmd)
        return out

    def persist_to_tmp(self, root, paths):
        files = self.exec('cd {}&& echo `pwd`/`ls -d {}`'.format(root, paths)).stdout.splitlines()
        for file in files:
            if not self._copy_file_to_workspace(file):
                return False
        return True

    def _copy_file_to_workspace(self, src):
        info = _exec(['docker', 'cp', '{}:{}'.format(self.name, src), '/tmp/lcircle/{}'.format(self.exec_uuid)])
        if info.returncode == 0:
            return True
        print('persist to workspace failed: {}'.format(info))

    def copy_workspace_to_container(self, dest):
        self.exec('mkdir -p {}'.format(dest))
        base_path = '/tmp/lcircle/{}'.format(self.exec_uuid)
        for file in os.listdir(base_path):
            info = _exec(['docker', 'cp', '/tmp/lcircle/{}/{}'.format(self.exec_uuid, file), '{}:{}'.format(self.name, dest)])
            if info:
                continue
            else:
                print('attach workspace failed: {}'.format(info))
                return False
        return True

    @property
    def duration(self):
        if self._duration is not None:
            return self._duration
        return time.time() - self._start_time

    def stop(self):
        self._stop()
        self._duration = time.time() - self._start_time


class Job:
    def __init__(self, name, exec_uuid, clone_url, spec, env_vars=None, requires=None):
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

    def run(self):
        self.state = Status.running
        print('---- Running Job: {} ----'.format(self.name))
        for step in self.steps:
            print('Executing Step: {}'.format(str(step)))
            output = step.run()
            if not output:
                print('ERROR: Job[{}]\n{}'.format(self.name, output.output))
                self.state = Status.failed
                return
        print('Job ({}) Passed in {} seconds'.format(self.name, self.docker.duration))
        self.state = Status.passed


class Step:
    def __init__(self, docker, *args):
        self.docker = docker
        self.init(*args)

    def init(self, *args):
        pass

    @classmethod
    def factory(cls, docker, step=None):
        if step == 'checkout':
            return CheckoutStep(docker)
        elif step.get('run'):
            return RunStep(docker, step.get('run'))
        elif step.get('persist_to_workspace'):
            return PersistStep(docker, step.get('persist_to_workspace'))
        elif step.get('attach_workspace'):
            return AttachStep(docker, step.get('attach_workspace'))
        raise NotImplementedError('FUCKED {}'.format(step))

    def run(self):
        raise NotImplementedError()


class PersistStep(Step):
    def init(self, spec):
        self.root = spec.get('root')
        self.paths = spec.get('paths')

    def run(self):
        out = self.docker.persist_to_tmp(self.root, self.paths)
        return out

    def __str__(self):
        return 'persist_to_workspace: root({}) paths({})'.format(self.root, self.paths)


class AttachStep(Step):
    def init(self, spec):
        self.at = spec.get('at')

    def run(self):
        out = self.docker.copy_workspace_to_container(self.at)
        return out

    def __str__(self):
        return 'attach_workspace: {}'.format(self.at)


class CheckoutStep(Step):
    def run(self):
        out = self.docker.exec('git clone {} .'.format(self.docker.clone_url))
        return out

    def __str__(self):
        return 'checkout'


class RunStep(Step):
    def init(self, spec):
        self.name = spec.get('name')
        self.command = spec.get('command')

    def run(self):
        out = self.docker.exec(self.command)
        return out

    def __str__(self):
        return '{}\n{}'.format(self.name, self.command)


def main(repo_slab=None, args=None):
    if args is None:
        parser = argparse.ArgumentParser(description='Run circleci jobs locally through docker')
        parser.add_argument('--env', type=str, nargs='+', help='K=V environment vars to pass to the test')
        parser.add_argument('--noclean', type=bool, help='dont remove /tmp/lcircle files or docker containers')
        args = parser.parse_args()

    if repo_slab is None:
        # This is insanely nasty and likely fragile as fuck - it takes a list of gir remotes and decodes
        # the github slab (chestm007/lcircle) from it. supports git and http as of now, but will likely
        # support most other types.
        def get_slab(in_):
            return '/'.join(in_.split(':')[-1].replace('.git', '').split('/')[-2:])

        for line in _exec(['git', 'remote', '-v']).stdout.splitlines():
            if '(fetch)' in line:
                repo_slab = get_slab(line.split()[1])

    if not repo_slab:
        print('not in the root directory of a git repository, exiting')
        sys.exit(1)

    def run_job(in_job_name):
        job = jobs[in_job_name]
        if job.requires is not None:
            for dep_job in job.requires:
                if not run_job(dep_job):
                    job.state = Status.failed
                    return False
        if job.state == Status.passed:
            return True
        if job.state == Status.failed:
            return False
        job.run()
        if job.state == Status.passed:
            return True
        return False

    exec_uuid = uuid.uuid4().hex
    try:
        os.mkdir('/tmp/lcircle')
    except FileExistsError:
        pass
    os.mkdir('/tmp/lcircle/{}'.format(exec_uuid))
    clone_url = 'https://github.com/{}.git'.format(repo_slab)
    _verify_deps_exist()
    config = _load_circle_config()
    jobs = {}
    for name, workflow in config.get('workflows').items():
        if name == 'version':
            continue
        jobs = {}
        for name in workflow['jobs']:
            requires = None
            if type(name) == dict:
                requires = list(name.values())[0].get('requires')
                name = list(name.keys())[0]
            jobs[name] = Job(name, exec_uuid, clone_url, config['jobs'].get(name), requires=requires, env_vars=args.env)
        for job_name in jobs.keys():
            run_job(job_name)
    for completed_job_name, completed_job in jobs.items():
        if not args.noclean:
            completed_job.docker.stop()
        if completed_job.state != Status.passed:
            return False
    if args.noclean:
        return True
    shutil.rmtree('/tmp/lcircle/{}'.format(exec_uuid))


def _load_circle_config():
    with open('.circleci/config.yml') as f:
        config = yaml.load(f, yaml.Loader)
    return config


def _verify_deps_exist():
    for binary in ('docker', 'git'):
        try:
            _exec(binary)
        except FileNotFoundError:
            print('{} not installed'.format(binary))


if __name__ == '__main__':
    main()
