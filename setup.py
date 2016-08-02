from setuptools import setup, find_packages
from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='fdm',
    version='1.0.1',
    description='An opinionated helper to deploy docker images',
    long_description=long_description,
    url='https://github.com/steffenmllr/fabric-docker-microservices',
    author='Steffen Mueller',
    author_email='steffen@mllrsohn.com',
    license='MIT',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2.7'
    ],
    install_requires=[
        'Fabric',
        'pytoml'
    ]
)