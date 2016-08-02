# -*- coding: utf-8 -*-
from fabric.api import env, task, run, local, cd, lcd, execute
import os
from fdm import *
from fdm import deploy, setStage, setContainer, _run

# Setup Stages
env.STAGES = ['staging']
env.configDir = "./"

# Only Show these commmands
__all__ = [
    'deploy',
    'build',
    'running',
    'run',
    'before_deploy',
    'deploy_all'
]

# Before Deploy Hook
def before_deploy(containerImage=False):
    print containerImage
    pass

@setStage
def deploy_all(stage=False):
    execute("deploy", stage=stage, container="app_1")
    execute("deploy", stage=stage, container="app_2")

