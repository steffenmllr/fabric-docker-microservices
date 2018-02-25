import os
from colorama import Fore
from fabric import Connection
from colorama import Style
import pytoml as toml
import json
import time
import datetime
import math
import sys

#
# Helper Functions
#
def getConfig(configDir, stage):
    configPath = os.path.join(configDir, "{stage}.toml".format(stage=stage))
    try:
        with open(configPath, 'rb') as fin:
            config = toml.load(fin)
            dump = json.dumps(config)
            json_str = os.path.expandvars(dump)
            config = json.loads(json_str)

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
            ctx = Connection(port=port, user=user, host=host)
            return config, ctx

    except FileNotFoundError:
        exitError("{configPath}' file not found".format(configPath=configPath))


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


def runInFolder(command, ctx, codeDir):
    return ctx.run("cd {codeDir} && {command}".format(codeDir=codeDir, command=command))

def setup(ctx, container):
    codeDir = container['code_dir']
    branch = container['branch']
    url = container['build']
    try:
        ctx.run("test -d {codeDir}".format(codeDir=codeDir), hide="both")
    except:
        ctx.run('rm -fr {codeDir}'.format(codeDir=codeDir))
        ctx.run('git clone --branch={branch} --depth=1 {url} {codeDir}'.format(branch=container['branch'], url=container['build'], codeDir=codeDir))

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
