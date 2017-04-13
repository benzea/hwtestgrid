#!/usr/bin/env python
from setuptools import setup

setup(name='dugrid',
      packages=['dugrid'],
      include_package_data=True,
      install_requires=[
          'flask',
      ],
      setup_requires=[
          'pytest-runner',
      ],
      tests_require=[
          'pytest',
      ],)
