import sys
import os
sys.path.append( os.path.join( os.path.dirname(__file__), os.path.pardir ) )
from invoke import Collection, task
from invoke.executor import Executor
from fdm.fdm import *


@task
def before_deploy(ctx, image, commands):
    print(image)
    print(commands)


@task
def after_deploy(ctx, image, commands):
    print(image)
    print(commands)

@task
def shell(ctx, stage="staging"):
    runCommands = getRunCommand(ctx=ctx, container="app_1", stage=stage)
    print(runCommands)


# Needed To call Tasks from each other (before_deploy/after_deploy)
# https://github.com/pyinvoke/invoke/issues/170#issuecomment-134927763
namespace = Collection(
    deploy,
    shell,
    redirects,
    database,
    interactive,
    before_deploy,
    after_deploy
)

def invoke_execute(context, command_name, **kwargs):
    """
    Helper function to make invoke-tasks execution easier.
    """
    results = Executor(namespace, config=context.config).execute((command_name, kwargs))
    target_task = context.root_namespace[command_name]
    return results[target_task]

namespace.configure({
    'configDir': "./",
    'root_namespace': namespace,
    'invoke_execute': invoke_execute,
})
