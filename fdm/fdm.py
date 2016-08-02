# -*- coding: utf-8 -*-
from fabric.api import env, task, run, local, cd, lcd, prompt, execute
from fabric import utils
from fabric.main import is_task_object
from fabric.contrib import console
import pytoml as toml
import json
import os
import time


# Only show Tasks in this list
__all__ = ['deploy', 'build', 'running', 'run']

# Configs
env.STAGES = []
os.environ["pwd"] = os.getcwd()


##
# Helper Functions
##
current_milli_time = lambda: int(round(time.time() * 1000))
def _stage_set(stage_name=False):
    configPath = os.path.join(env.configDir, "%s.toml" % (stage_name))
    with open(configPath, 'rb') as fin:
        config = toml.load(fin)

    dump = json.dumps(config)
    json_str = os.path.expandvars(dump)
    config = json.loads(json_str)

    env.stage = stage_name
    for option, value in config.items():
        setattr(env, option, value)

    return config

def setStage(f):
    def nf(*args, **kwargs):
        stage = kwargs.get('stage', None)
        if not stage or stage not in env.STAGES:
            utils.abort("You need to provide a valid stage")
        else:
            _stage_set(stage)
        return f(*args, **kwargs)
    return nf


def setContainer(f):
    def nf(*args, **kwargs):
        container = kwargs.get('container', None)
        container = env.containers.get(container, None)
        if not container:
            utils.abort("Could not find container")
        else:
            setattr(env, 'container', container)

        return f(*args, **kwargs)
    return nf

def _folderExists(repopath):
    if env.stage == 'local':
        return os.path.isdir(repopath)
    else:
        return exists(repopath, True, True)


def _run(command, capture=False):
    if env.stage == 'local':
        return local(command, capture)
    else:
        return run(command, capture)

def _cd(command):
    if env.stage == 'local':
        return lcd(command)
    else:
        return cd(command)

##
# Tasks
##

@setStage
@setContainer
@task
def running(stage=False, container=False):
    """
    Get the Running Container
    """
    cmd = 'docker ps | grep "%s_%s" | awk \'{print $1}\'' % (env.stage,env.container['name'],)
    return _run(cmd, capture=True).strip().splitlines()


@setStage
@setContainer
@task
def setup(stage=False, container=False):
    """
    Setups the repo
    """
    _run('rm -fr {repopath}'.format(repopath=env.container['code_dir']))
    _run('git clone --branch={branch} --depth=1 {url} {repopath}'.format(branch=env.container['branch'],url=env.container['build'],repopath=env.container['code_dir']))


@setStage
@setContainer
@task
def build(stage=False, container=False):
    """
    Build or pull a container
    """
    hasImage = env.container.get('image', None)
    hasBuild = env.container.get('build', None)
    if not hasImage and not hasBuild:
        utils.abort("No image or build path defined")
    if hasImage:
        _run("docker pull {image}".format(image=hasImage))
        return hasImage

    if hasBuild:
        if not _folderExists(env.container['code_dir']):
            setup(stage=stage, container=container)
        else:
            with _cd(env.container['code_dir']):
                _run('git fetch origin')
                _run('git checkout {branch}'.format(branch=env.container['branch']))
                _run('git reset --hard')
                _run('git clean -d -x -f')
                _run('git pull origin {branch}'.format(branch=env.container['branch']))

                gitHash = _run("git describe --always", capture=True).strip()
                tagName = "{containerName}_{stage}/{gitHash}".format(containerName=env.container['name'], gitHash=gitHash, stage=stage)
                _run('docker build --tag {tagName} .'.format(tagName=tagName))
                return tagName

@setStage
@setContainer
@task
def deploy(stage=False, container=False):
    """
    Build and restart a container
    """
    runningContainers = running(stage=stage, container=container)
    containerImage = build(stage=stage, container=container)
    deploy_time = current_milli_time()

    # Stop Running container
    def _stop():
        # Stop Running Container
        for container in runningContainers:
            _run('docker rm -f {container}'.format(container=container))

    # Build Run Command
    command = [
        "sudo",
        "docker",
        "run",
        "--name {stage}_{containerName}_{deploy_time}".format(containerName=env.container['name'], stage=env.stage, deploy_time=deploy_time),
        "-d",
        "--restart=always",
    ]

    # Environment
    environments = env.container.get('environments', [])
    for environment in environments:
        command.append("-e {environment}".format(environment=environment))

    # Volumes
    volumes = env.container.get('volumes', [])
    for volume in volumes:
        command.append("-v {volume}".format(volume=volume))

    # Ports
    ports = env.container.get('ports', [])
    for port in ports:
        command.append("-p {port}".format(port=port))

    # Other Commands
    cmds = env.container.get('cmds', [])
    for cmd in cmds:
        command.append(cmd)

    # Image
    command.append(containerImage)

    # Join Command
    command = " ".join(map(str, command))

    # Check for before Hooks
    hook_before_deploy = env.container.get('hook_before_deploy', None)
    if hook_before_deploy:
        execute(hook_before_deploy, containerImage=containerImage)

    # If we have exposed ports, we need to stop the container first
    if len(ports) > 0:
        _stop()

    # Run Container
    _run(command)

    # Stop if we don't have exposed ports
    if len(ports) == 0:
        _stop()

    # Check for after Hooks
    hook_after_deploy = env.container.get('hook_after_deploy', None)
    if hook_after_deploy:
        execute(hook_after_deploy, containerImage=containerImage)


@setStage
@setContainer
@task
def run(stage=False, container=False, cmd=False):
    """
    Run the container
    """

    containerImage = build(stage=stage, container=container)
    deploy_time = current_milli_time()

    # Build Run Command
    command = [
        "sudo",
        "docker",
        "run",
        "--name run_{stage}_{containerName}_{deploy_time}".format(containerName=env.container['name'], stage=env.stage, deploy_time=deploy_time),
        "-it",
        containerImage,

    ]

    # Image
    if cmd:
        command.append("sh -c")
        command.append("\"%s\"" % cmd)
    else:
        command.append("/bin/sh")

    # Join Command
    command = " ".join(map(str, command))

    # Run Container
    _run(command)
