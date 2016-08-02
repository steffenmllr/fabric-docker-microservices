# -*- coding: utf-8 -*-
from fabric.api import env, task, run, local, cd, lcd, execute
from fdm import *
from fdm import deploy, settings, loadConfig

# Setup Stages
env.STAGES = ['staging']
env.configDir = "./"

# Load the config
loadConfig(stages=['staging'], configDir="./")

# Before Deploy Hook
def before_deploy(image, commands):
    print "before_deploy"
    print image
    print commands

# Deploy multiple containers
def deploy_all(stage=False):
    execute("running", container="app_1")
    execute("running", container="app_2")

# Only Show these commmands
__all__ = [
    'deploy',
    'build',
    'running',
    'run',
    'before_deploy',
    'deploy_all'
]
