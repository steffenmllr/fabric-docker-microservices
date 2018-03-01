import os
import sys
from invoke import Collection, task
from colorama import Fore, init, Back
from .helpers import *
import requests
import ssl
import socket
import traceback

init(autoreset=True)

#
# PWD
#
os.environ["pwd"] = os.getcwd()

#
# Tasks
#
# @task
# def status(ctx, container="", stage="staging"):
#     config, ctx = getConfig(ctx.configDir, stage)
#     for name in config['containers']:
#         cmd = 'docker ps | grep "%s_%s" | awk \'{print $1}\'' % (stage, config['containers'][name]['name'],)
#         runningContainers = ctx.run(cmd).stdout.strip().splitlines()
#         if len(runningContainers) > 0:
#             print(Fore.GREEN + "{stage}_{name} is running {size} container".format(name=name, stage=stage, size=len(runningContainers)))
#         else:
#             print(Fore.RED + "{stage}_{name} is NOT running".format(name=name, stage=stage))

# @task
# def runnning(ctx, container="", stage="staging"):
#     config, ctx = getConfig(ctx.configDir, stage)
#     container = getContainer(config, container)
#     cmd = 'docker ps | grep "%s_%s" | awk \'{print $1}\'' % (stage, container['name'],)
#     return ctx.run(cmd).stdout.strip().splitlines()


@task
def deploy(ctx, container="", stage="staging", ignoreHooks=False):
    start = time.time()
    config, remoteCtx = getConfig(ctx.configDir, stage)
    containerSettings = getContainer(config, container)

    # Status
    getStatus(remoteCtx, config, stage)


    # Containers Running
    runningContainers = getRunning(remoteCtx=remoteCtx, container=containerSettings, stage=stage)
    deploy_time = current_milli_time()

    # Stop Running container
    def _stop():
        # Stop Running Container
        for runningContainer in runningContainers:
            remoteCtx.run('docker rm -f {container}'.format(container=runningContainer))

    # Get the container to run
    containerImage = getBuild(remoteCtx=remoteCtx, container=containerSettings, stage=stage)

    if 'displayName' in container:
        displayName = "{stage}_{containerName}".format(stage=stage, containerName=containerSettings['displayName'])
    else:
        displayName = "{stage}_{containerName}_{deploy_time}".format(containerName=containerSettings['name'], stage=stage, deploy_time=deploy_time)


    # Build Run Command
    command = [
        "docker",
        "run",
        "--name {displayName}".format(displayName=displayName),
        "-d",
        "-e CURRENT_RELEASE='{currentRelease}'".format(currentRelease=containerImage),
        "--restart=always",
    ]

    additionalCommands = getAdditionalDockerCommands(containerSettings)

    # Check for before Hooks
    try:
        hook_before_deploy = ctx[containerSettings.get('hook_before_deploy', None)]
        if hook_before_deploy:
            hook_before_deploy(ctx=remoteCtx, image=containerImage, commands=list(additionalCommands))
    except Exception:
        pass

    # Merge commands
    command = command + additionalCommands

    # Image
    command.append(containerImage)

    # Add Run Options
    cmds = containerSettings.get('options', [])
    for cmd in cmds:
        command.append(cmd)

    # Join Command
    command = " ".join(map(str, command))

    ports = containerSettings.get('ports', [])
    # If we have exposed ports, we need to stop the container first
    if len(ports) > 0:
        _stop()

    # Run Container
    remoteCtx.run(command)

    # Stop if we don't have exposed ports
    if len(ports) == 0:
        _stop()

    # Check for before Hooks
    try:
        hook_after_deploy = ctx[containerSettings.get('hook_after_deploy', None)]
        if hook_after_deploy:
            hook_after_deploy(ctx=remoteCtx, image=containerImage, commands=list(additionalCommands))
    except Exception:
        pass

    seconds = time.time() - start
    completed = human_time(seconds=seconds)

    print(Fore.GREEN + "Deployment completed in {completed}".format(completed=completed))

    return {'stage': stage, 'container': container}


@task
def build(ctx, container="", stage="staging"):
    config, remoteCtx = getConfig(ctx.configDir, stage)
    container = getContainer(config, container)

    return getBuild(remoteCtx, container, stage)


def getRunCommand(ctx, container, stage, cmd="", rebuild=True):
    config, ctx = getConfig(ctx.configDir, stage)

    if rebuild:
        containerImage = build(ctx, container, stage)
    else:
        containerImage = "{containerName}/{stage}:latest".format(containerName=container, stage=stage)

    container = getContainer(config, container)
    deploy_time = current_milli_time()

    # Build Run Command
    command = [
        "docker",
        "run",
        "-e CURRENT_RELEASE='{currentRelease}'".format(currentRelease=containerImage),
        "--name run_{stage}_{containerName}_{deploy_time}".format(containerName=container['name'], stage=stage, deploy_time=deploy_time),
        "-i"
    ]

    # Env vars
    command = command + getAdditionalDockerCommands(container)

    # Append Image
    command.append(containerImage)

    # Image
    if cmd:
        command.append("sh -c")
        command.append("\"%s\"" % cmd)

    # Join Command
    command = " ".join(map(str, command))

    # Run Container
    return command

@task
def interactive(ctx, container="", stage="staging"):
    runCommands = getRunCommand(ctx=ctx, container="app_1", stage=stage, cmd="/bin/sh", rebuild=False)
    print("Running: {runCommands}".format(runCommands=runCommands))
    ctx.run(runCommands)



@task
def redirects(ctx, stage="staging"):
    config = getConfig(ctx.configDir, stage, connect=False)
    redirects = getRedirects(config)

    # Testing the Sites
    for site in redirects:
        print("\n👾 Testing {num} redirects for {url}\n".format(url=site['target_url'], num=len(site['site_urls'])))
        for url in site['site_urls']:
            try:
                r = requests.get(url, verify=True)
                # Test if we get a 200er, the wanted target url and check if we have some content
                if r.status_code != 200 or r.url != site['target_url'] or len(r.content) < 1000:
                    print("❌ {url} has wrong redirection or empty response".format(url=url))

                # If we have SSL we check how many days are left
                info = Fore.GREEN + "✔️   {url}".format(url=url)

                if 'https' in url:
                    hostname = url.replace("https://", "")
                    ssl_date_fmt = r'%b %d %H:%M:%S %Y %Z'
                    context = ssl.create_default_context()
                    conn = context.wrap_socket(
                        socket.socket(socket.AF_INET),
                        server_hostname=hostname,
                    )
                    conn.settimeout(5.0)
                    conn.connect((hostname, 443))
                    ssl_info = conn.getpeercert()
                    expires_at =  datetime.datetime.strptime(ssl_info['notAfter'], ssl_date_fmt)
                    delta = abs((datetime.datetime.now()).date() - expires_at.date()).days
                    info = info + " - SSL is valid for {delta} days".format(delta=delta)

                # Print out report
                print("{info}".format(info=info))

            except Exception as error:
                # Mostly can't connect or a ssl error
                print(Fore.RED + "❌   {url} - {error}".format(url=url, error=error))


@task
def database(ctx, name="", stage="staging"):
    config, remoteCtx = getConfig(ctx.configDir, stage)
    dbconfig = getDatabaseConfig(config, name)

    # Generate Filename
    timestamp = current_milli_time()
    backup_file = "{databaseName}-{stage}-snapshot-{timestamp}".format(databaseName=name, stage=stage, timestamp=timestamp)
    ctx.run('mkdir -p {backupFolder}'.format(backupFolder=dbconfig['backup_dir']))

    # Remote Backup Folder
    ctx.run('mkdir -p /tmp/backups/database')

    # Backup Command
    backup_command = " ".join(map(str, [
        "PGPASSWORD={remotePassword}".format(remotePassword=dbconfig['remote_password']),
        "pg_dump",
        "-p {port}".format(port=dbconfig['remote_port']),
        "-h {host}".format(host=dbconfig['remote_host']),
        "-U {user}".format(user=dbconfig['remote_user']),
        "-F c -b -v",
        "-f /backups/{backup_file}".format(backup_file=backup_file),
        "{databaseName}".format(databaseName=dbconfig['remote_database'])
    ]))

    # Docker Backup Command
    command = " ".join(map(str, [
        "docker",
        "run",
        "-v /tmp/backups/database:/backups",
        "-i",
        dbconfig['image'],
        "sh",
        "-c",
        "\"{backup_command}\"".format(backup_command=backup_command)
    ]))

    print(Fore.YELLOW + "Running Backup Command with image: '{image}':\n".format(image=dbconfig['image']) + Style.DIM + backup_command)

    remoteCtx.run(command, hide="both")

    remotePath = '/tmp/backups/database/{backup_file}'.format(backup_file=backup_file)
    localPath = os.path.join(dbconfig['backup_dir'], backup_file)
    print(Fore.YELLOW + "\nDownloading: '{backup_file}' to: \n".format(backup_file=backup_file) + Style.DIM + dbconfig['backup_dir'] + "\n")

    remoteCtx.get(remotePath, localPath)

    # Replace local database
    if confirm("Do you want to replace your local '{databaseName}' databases".format(databaseName=dbconfig['local_database'])):
        dropDB_command = "dropdb -U {user} {databaseName}".format(user=dbconfig['local_user'], databaseName=dbconfig['local_database'])
        createDB_command = "createdb -U {user} {databaseName}".format(user=dbconfig['local_user'], databaseName=dbconfig['local_database'])
        restore_command = " ".join(map(str, [
            "PGPASSWORD={remotePassword}".format(remotePassword=dbconfig['local_password']),
            "pg_restore",
            "-p {port}".format(port=dbconfig['local_port']),
            "-U {user}".format(user=dbconfig['local_user']),
            "-d {databaseName}".format(databaseName=dbconfig['local_database']),
            "-v {backupFolder}/{backup_file}".format(backupFolder=dbconfig['backup_dir'], backup_file=backup_file)
        ]))

        print(Fore.YELLOW + "\nReplacing: '{databaseName}' to: \n".format(databaseName=dbconfig['local_database']) + Style.DIM + dropDB_command + '\n' + createDB_command + '\n' + restore_command)

        ctx.run(dropDB_command, hide="both")
        ctx.run(createDB_command, hide="both")
        ctx.run(restore_command, hide="both")
