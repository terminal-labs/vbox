import sys
from setuptools import setup, find_packages

setup(
    name="vbox",
    version="0.0.1",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=[
        "setuptools",
        "fastapi",
        "click",
    ],
    entry_points="""
      [console_scripts]
      vbox=vbox.vboxclient:main
  """,
)
