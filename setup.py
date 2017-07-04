#!/usr/bin/env python
from setuptools import setup

setup(name='hwtestgrid',
      packages=['hwtestgrid'],
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
