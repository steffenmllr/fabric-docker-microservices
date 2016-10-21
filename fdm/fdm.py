# -*- coding: utf-8 -*-
from fabric.api import env, task, run, local, cd, lcd, prompt, execute, sudo, roles, get, hide
from fabric import utils
from fabric.main import is_task_object
from fabric.colors import red, green
from fabric.contrib import console
from fabric.contrib.files import exists
from functools import wraps
import pytoml as toml
import json
import os
import time


# Only show Tasks in this list
__all__ = ['deploy', 'build', 'running', 'stage' '_run', 'interactive', 'backup_db']

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


def _getAdditionalDockerCommands(container):
    additionalCommands = []

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

    return additionalCommands

##
# Tasks
##

#
def settings(stage, container=False):
    """
    Sets the stage and the container
    """

    config = env.roledefs[stage]
    env.container = False
    _stage_set(stage, config)
    if container:
        container = env.containers[container]
        setattr(env, 'container', container)


# Checks for settings
def checkSettings(f):
    @wraps(f)
    def wrapper(*args, **kwds):
        stage = kwds.get('stage', env.stage)
        container = kwds.get('container', env.container)

        if not stage:
            utils.abort("Need to set a stage")

        if container:
            if isinstance(container, str):
                container = env.containers[container]

        if not container:
            utils.abort("Need to set a container")

        kwds_dic = {'container': container, 'stage': stage}

        # Command
        cmd = kwds.get('cmd', False)
        if cmd:
            kwds_dic['cmd'] = cmd

        # Commands
        commands = kwds.get('commands', False)
        if cmd:
            kwds_dic['commands'] = commands

        return f(*args, **kwds_dic)
    return wrapper


def checkDatabseSettings(f):
    @wraps(f)
    def wrapper(*args, **kwds):
        stage = env.stage
        if not stage:
            utils.abort("Need to set a stage")

        if not args:
            utils.abort("Need to set a database")

        try:
            database =  env.roledefs[stage]['database'][args[0]]
        except KeyError:
            utils.abort("Database not found")

        kwds_dic = {'stage': stage, 'database':database, 'name': args[0]}
        kargs = []

        return f(*kargs, **kwds_dic)
    return wrapper


@checkSettings
@task
def running(stage, container):
    """
    Get the Running Container
    """
    with hide('output', 'running'):
        cmd = 'docker ps | grep "%s_%s" | awk \'{print $1}\'' % (stage, container['name'],)
        result = _run(cmd, capture=True).strip().splitlines()
        return result


def status():
    """
    Checks if all the containers are running
    """

    stage = env.stage
    if not stage:
        utils.abort("Need to set a stage")


    for name, container in env.containers.items():
        runningContainers = running(stage=stage, container=container)
        if len(runningContainers) > 0:
            print green("{stage}_{name} is running {size} container".format(name=name, stage=stage, size=len(runningContainers)))
        else:
            print red("{stage}_{name} is NOT running".format(name=name, stage=stage))



@checkSettings
@task
def setup(stage, container):
    """
    Setups the repo
    """

    _run('rm -fr {repopath}'.format(repopath=container['code_dir']))
    _run('git clone --branch={branch} --depth=1 {url} {repopath}'.format(branch=container['branch'],url=container['build'],repopath=container['code_dir']))



@checkSettings
@task
def build(stage, container):
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

        with _cd(container['code_dir']):
            _run('git fetch origin')
            _run('git checkout {branch}'.format(branch=container['branch']))
            _run('git reset --hard')
            _run('git clean -d -x -f')
            _run('git pull origin {branch}'.format(branch=container['branch']))

            gitHash = _run("git describe --always", capture=True).strip()
            tagName = "{containerName}/{stage}:{gitHash}".format(containerName=container['name'], gitHash=gitHash, stage=stage)
            tagNameLastest = "{containerName}/{stage}:latest".format(containerName=container['name'], stage=stage)

            # Check if the image exists
            exists = _run('docker images -q %s | awk \'{print $1}\'' % (tagName)).strip().splitlines()
            if len(exists) != 0:
                print "\n" + red("Image {tagName} already exists, skip building".format(tagName=tagName)) + "\n"
                return tagName


            command = " ".join(map(str, [
                "docker",
                "build",
                "--tag {tagName}".format(tagName=tagName),
                "--tag {tagNameLastest}".format(tagNameLastest=tagNameLastest),
                "."
            ]))

            with _cd(container.get('build_path', container['code_dir']) ):
                _run(command)

            return tagName


@checkSettings
@task
def deploy(stage, container):
    """
    Build and restart a container: (fab settings:stage=staging,container=app_1 deploy)
    """
    execute("status");
    start = time.time()

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

    additionalCommands = _getAdditionalDockerCommands(container)

    # Check for before Hooks
    hook_before_deploy = container.get('hook_before_deploy', None)
    if hook_before_deploy:
        execute(hook_before_deploy, image=containerImage, commands=list(additionalCommands))

    # Merge commands
    command = command + additionalCommands

    # Image
    command.append(containerImage)

    # Join Command
    command = " ".join(map(str, command))

    ports = container.get('ports', [])
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
        execute(hook_after_deploy, image=containerImage, commands=list(additionalCommands))

    end = time.time()
    duration = end - start
    minutes, seconds = divmod(duration, 60)

    print green("Deployment completed in {minutes}:{seconds}".format(minutes=minutes, seconds=seconds))

    return {'stage': stage, 'container': container}

@checkSettings
@task
def interactive(stage=False, container=False, cmd=False, commands=False, rebuild=True):
    """
    Run the container -it
    """
    if rebuild:
        containerImage = build(stage=stage, container=container)
    else:
        containerImage = "{containerName}/{stage}:latest".format(containerName=container['name'], stage=stage)

    deploy_time = current_milli_time()

    # Build Run Command
    command = [
        "sudo",
        "docker",
        "run",
        "--name run_{stage}_{containerName}_{deploy_time}".format(containerName=container['name'], stage=stage, deploy_time=deploy_time),
        "-it"
    ]

    # Env vars
    if commands:
        command = command + commands
    else:
        command = command + _getAdditionalDockerCommands(container)

    # Append Image
    command.append(containerImage)

    # Image
    if cmd:
        command.append("sh -c")
        command.append("\"%s\"" % cmd)

    # Join Command
    command = " ".join(map(str, command))

    # Run Container
    _run(command)

    return {'stage': stage, 'container': container, 'cmd': cmd}


@checkDatabseSettings
@task
def backup_db(stage, database, name):
    """
    Backups and pg db and restores it locally (fab settings:stage=staging,database=db_1 backup_db)
    """

    # Generate Filename
    timestamp = current_milli_time()
    backup_file = "{databaseName}-{stage}-snapshot-{timestamp}".format(databaseName=name, stage=stage, timestamp=timestamp)

    # Generate local Backup Folder
    local('mkdir -p {backupFolder}'.format(backupFolder=database['backup_dir']))

    # Remote Backup Folder
    _run('mkdir -p /tmp/backups/database')

    # Backup Command
    backup_command = " ".join(map(str, [
        "PGPASSWORD={remotePassword}".format(remotePassword=database['remote_password']),
        "pg_dump",
        "-i",
        "-p {port}".format(port=database['remote_port']),
        "-h {host}".format(host=database['remote_host']),
        "-U {user}".format(user=database['local_user']),
        "-F c -b -v",
        "-f /backups/{backup_file}".format(backup_file=backup_file),
        "{databaseName}".format(databaseName=database['remote_database'])
    ]))

    # Docker Backup Command
    command = " ".join(map(str, [
        "docker",
        "run",
        "-v /tmp/backups/database:/backups",
        "-it",
        database['image'],
        "sh",
        "-c",
        "\"{backup_command}\"".format(backup_command=backup_command)
    ]))

    # Run Command
    _run(command)

    # Get the Backup
    if stage is not 'local':
        get('/tmp/backups/database/{backup_file}'.format(backup_file=backup_file), database['backup_dir'])

    # Restore the local database
    if console.confirm("Do you want to replace your local '{databaseName}' databases".format(databaseName=database['local_database'])):
        local("dropdb -U {user} {databaseName}".format(user=database['local_user'], databaseName=database['local_database']))
        local("createdb -U {user} {databaseName}".format(user=database['local_user'], databaseName=database['local_database']))
        restore_command = " ".join(map(str, [
            "PGPASSWORD={remotePassword}".format(remotePassword=database['remote_password']),
            "pg_restore",
            "-p {port}".format(port=database['local_port']),
            "-U {user}".format(user=database['local_user']),
            "-d {databaseName}".format(databaseName=database['local_database']),
            "-v {backupFolder}/{backup_file}".format(backupFolder=database['backup_dir'], backup_file=backup_file)
        ]))

        local(restore_command)

