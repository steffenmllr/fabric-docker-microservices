import os
from colorama import Fore
from fabric import Connection
from invocations.console import confirm
from colorama import Style, Fore, init, Back
import pytoml as toml
import json
import time
import datetime
import math
import sys
from dotenv import load_dotenv

#
# Helper Functions
#
def getConfig(configDir, stage, connect=True):
    configPath = os.path.join(configDir, "{stage}.toml".format(stage=stage))
    try:
        with open(configPath, 'rb') as fin:
            config = toml.load(fin)
            try:
                env = config['dotenv']
                load_dotenv(env, verbose=True)
            except:
                pass

            dump = json.dumps(config)
            json_str = os.path.expandvars(dump)
            config = json.loads(json_str)

            if connect:
                # remote Connection
                try:
                    port = config['server']['port']
                except:
                    port = 22

                host = config['server']['host']
                user = config['server']['user']

                print(Fore.YELLOW + '\n\n=====================================================')
                print(Style.BRIGHT  + "🏰 Connecting to {user}@{host}:{port} - '{stage}'".format(user=user, host=host, port=port, stage=stage))
                print(Fore.YELLOW + '=====================================================\n')
                remoteCtx = Connection(port=port, user=user, host=host)
                return config, remoteCtx
            else:
                return config

    except FileNotFoundError:
        exitError("{configPath}' file not found".format(configPath=configPath))

def getStatus(remoteCtx, config, stage):
    for name in config['containers']:
        cmd = 'docker ps | grep "%s_%s" | awk \'{print $1}\'' % (stage, config['containers'][name]['name'],)
        runningContainers = remoteCtx.run(cmd).stdout.strip().splitlines()
        if len(runningContainers) > 0:
            print(Fore.GREEN + "{stage}_{name} is running {size} container".format(name=name, stage=stage, size=len(runningContainers)))
        else:
            print(Fore.RED + "{stage}_{name} is NOT running".format(name=name, stage=stage))

def getRunning(remoteCtx, container, stage):
    cmd = 'docker ps | grep "%s_%s" | awk \'{print $1}\'' % (stage, container['name'],)
    return remoteCtx.run(cmd).stdout.strip().splitlines()

def getBuild(remoteCtx, container, stage="staging"):

    hasImage = container.get('image', None)
    hasBuild = container.get('build', None)

    if not hasImage and not hasBuild:
        exitError("No image or build path defined")

    if hasImage:
        remoteCtx.run("docker pull {image}".format(image=hasImage))
        return hasImage

    # Setup
    setup(remoteCtx=remoteCtx, container=container)

    codeDir = container['code_dir']
    branch = container['branch']

    # Check out repo
    with remoteCtx.cd(codeDir):
        remoteCtx.run("git checkout {branch}".format(branch=branch))
        remoteCtx.run("git reset --hard && git clean -d -x -f")
        remoteCtx.run("git pull origin {branch}".format(branch=branch))

        gitHash = remoteCtx.run("git describe --always", hide="out").stdout.strip()
        tagName = "{containerName}/{stage}:{gitHash}".format(containerName=container['name'], gitHash=gitHash, stage=stage)
        tagNameLastest = "{containerName}/{stage}:latest".format(containerName=container['name'], stage=stage)

        # Check if the image exists
        exists = remoteCtx.run('docker images -q %s | awk \'{print $1}\'' % (tagName)).stdout.strip().splitlines()
        if len(exists) != 0:
            print("\n\n")
            if confirm(Back.GREEN + Fore.BLACK + "Image {tagName} already exists, skip building ?".format(tagName=tagName)):
                return tagName

        builCommands = [
            "docker",
            "build",
            "--tag {tagName}".format(tagName=tagName),
            "--tag {tagNameLastest}".format(tagNameLastest=tagNameLastest)
        ]

        buildArguments = container.get('build_args', [])
        for command in buildArguments:
            builCommands.append(command)

        # Append Context
        builCommands.append(".")

        command = " ".join(map(str, builCommands))

        remoteCtx.run(command)

        return tagName


def getContainer(config, container):
    try:
        return config['containers'][container];
    except KeyError:
        exitError("Container '{container}' not found".format(container=container))
        sys.exit(1)


def getDatabaseConfig(config, dbconfig):
    try:
        return config['database'][dbconfig]
    except KeyError:
        exitError("Database {dbconfig} not found - please set them in the config".format(dbconfig=dbconfig))
        sys.exit(1)

def getRedirects(config):
    try:
        return config['redirects']
    except KeyError:
        exitError("Redirects not found - please set them in the config")
        sys.exit(1)



def getAdditionalDockerCommands(container):
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

    # Labels
    labels = container.get('labels', [])
    for label in labels:
        additionalCommands.append("-l {label}".format(label=label))

    # Other Commands
    cmds = container.get('cmds', [])
    for cmd in cmds:
        additionalCommands.append(cmd)

    return additionalCommands


def setup(remoteCtx, container):
    codeDir = container['code_dir']
    branch = container['branch']
    url = container['build']
    try:
        remoteCtx.run("test -d {codeDir}".format(codeDir=codeDir), hide="both")
    except:
        remoteCtx.run('rm -fr {codeDir}'.format(codeDir=codeDir))
        remoteCtx.run('git clone --branch={branch} --depth=1 {url} {codeDir}'.format(branch=container['branch'], url=container['build'], codeDir=codeDir))

current_milli_time = lambda: int(round(time.time() * 1000))

def exitError(msg="There was an Error"):
    print(Fore.RED + msg)
    sys.exit(1)


def human_time(*args, **kwargs):
    secs  = float(datetime.timedelta(*args, **kwargs).total_seconds())
    units = [("day", 86400), ("hour", 3600), ("minute", 60), ("second", 1)]
    parts = []
    for unit, mul in units:
        if secs / mul >= 1 or mul == 1:
            if mul > 1:
                n = int(math.floor(secs / mul))
                secs -= n * mul
            else:
                n = secs if secs != int(secs) else int(secs)
            parts.append("%s %s%s" % (n, unit, "" if n == 1 else "s"))
    return ", ".join(parts)
