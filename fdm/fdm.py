# -*- coding: utf-8 -*-
from fabric.api import env, task, run, local, cd, lcd, prompt, execute, runs_once, sudo, roles
from fabric import utils
from fabric.main import is_task_object
from fabric.contrib import console
import pytoml as toml
import json
import os
import time


# Only show Tasks in this list
__all__ = ['deploy', 'build', 'running', 'stage' '_run']

# Configs
#env.STAGES = []
os.environ["pwd"] = os.getcwd()

##
# Helper Functions
##
current_milli_time = lambda: int(round(time.time() * 1000))

def _stage_set(stage_name, config):
    env.stage = stage_name
    for option, value in config.items():
        setattr(env, option, value)

    return config

def checkStage(f):
    def nf(*args, **kwargs):
        if not env.stage:
            utils.abort("You need to provide a valid stage eg. fab stage=production deploy:redis")
        return f(*args, **kwargs)
    return nf

def checkContainer(f):
    def nf(*args, **kwargs):
        if not env.container:
            utils.abort("Could not find container in env")
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


def loadConfig(stages=[], configDir="./"):
    for stage_name in stages:
        configPath = os.path.join(configDir, "%s.toml" % (stage_name))
        with open(configPath, 'rb') as fin:
            config = toml.load(fin)

        dump = json.dumps(config)
        json_str = os.path.expandvars(dump)
        config = json.loads(json_str)
        env.roledefs[stage_name] = config

##
# Tasks
##

# Sets the stage and the container
def settings(stage=False, container=False):
    config = env.roledefs[stage]
    env.container = False
    _stage_set(stage, config)
    if container:
        container = env.containers[container]
        setattr(env, 'container', container)


# Checks for settings
def checkSettings(f):
    def nf(*args, **kwargs):
        stage = kwargs.get('stage', env.stage)
        container = kwargs.get('container', env.container)

        if not stage:
            utils.abort("Need to set a stage")

        if container:
            if isinstance(container, str):
                container = env.containers[container]

        if not container:
            utils.abort("Need to set a container")

        return f(stage=stage, container=container)
    return nf



@checkSettings
@task
def running(stage=False, container=False):
    """
    Get the Running Container
    """
    cmd = 'docker ps | grep "%s_%s" | awk \'{print $1}\'' % (stage,container['name'],)
    return _run(cmd).strip().splitlines()



@checkSettings
@task
def setup(stage=False, container=False):
    """
    Setups the repo
    """
    _run('rm -fr {repopath}'.format(repopath=container['code_dir']))
    _run('git clone --branch={branch} --depth=1 {url} {repopath}'.format(branch=container['branch'],url=container['build'],repopath=container['code_dir']))



@checkSettings
@task
def build(stage=False, container=False):
    """
    Build or pull a container
    """
    hasImage = container.get('image', None)
    hasBuild = container.get('build', None)
    if not hasImage and not hasBuild:
        utils.abort("No image or build path defined")
    if hasImage:
        _run("docker pull {image}".format(image=hasImage))
        return hasImage

    if hasBuild:
        if not _folderExists(container['code_dir']):
            setup(stage=stage, container=container)
        else:
            with _cd(container['code_dir']):
                _run('git fetch origin')
                _run('git checkout {branch}'.format(branch=container['branch']))
                _run('git reset --hard')
                _run('git clean -d -x -f')
                _run('git pull origin {branch}'.format(branch=container['branch']))

                gitHash = _run("git describe --always", capture=True).strip()
                tagName = "{containerName}_{stage}/{gitHash}".format(containerName=container['name'], gitHash=gitHash, stage=stage)

                command = [
                    "docker",
                    "build",
                    "--tag {tagName}".format(tagName=tagName),
                    "."
                ]

                command = " ".join(map(str, command))
                with _cd(container.get('build_path', container['code_dir']) ):
                    _run(command)

                return tagName


@checkSettings
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
        for runningContainer in runningContainers:
            _run('docker rm -f {container}'.format(container=runningContainer))

    # Build Run Command
    command = [
        "sudo",
        "docker",
        "run",
        "--name {stage}_{containerName}_{deploy_time}".format(containerName=container['name'], stage=stage, deploy_time=deploy_time),
        "-d",
        "--restart=always",
    ]

    additionalCommands = [];

    # Environment
    environments = container.get('environments', [])
    for environment in environments:
        additionalCommands.append("-e {environment}".format(environment=environment))

    # Volumes
    volumes = container.get('volumes', [])
    for volume in volumes:
        additionalCommands.append("-v {volume}".format(volume=volume))

    # Ports
    ports = container.get('ports', [])
    for port in ports:
        additionalCommands.append("-p {port}".format(port=port))

    # Other Commands
    cmds = container.get('cmds', [])
    for cmd in cmds:
        additionalCommands.append(cmd)

    # Check for before Hooks
    hook_before_deploy = container.get('hook_before_deploy', None)
    print hook_before_deploy
    if hook_before_deploy:
        execute(hook_before_deploy, image=containerImage, commands=additionalCommands)

    return

    # Merge commands
    command = command + additionalCommands

    # Image
    command.append(containerImage)

    # Join Command
    command = " ".join(map(str, command))

    # If we have exposed ports, we need to stop the container first
    if len(ports) > 0:
        _stop()

    # Run Container
    _run(command)

    # Stop if we don't have exposed ports
    if len(ports) == 0:
        _stop()

    # Check for after Hooks
    hook_after_deploy = container.get('hook_after_deploy', None)
    if hook_after_deploy:
        execute(hook_after_deploy, image=containerImage, commands=additionalCommands)


@checkSettings
@task
def interactive(stage=False, container=False, cmd=False):
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
        "--name run_{stage}_{containerName}_{deploy_time}".format(containerName=container['name'], stage=stage, deploy_time=deploy_time),
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
