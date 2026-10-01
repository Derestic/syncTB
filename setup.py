from setuptools import find_packages, setup

setup(
    name="synctb",
    version="0.1.0",
    description="Synchronise un tenant ThingsBoard PE depuis un dépôt de Version Control",
    packages=find_packages(exclude=["tests", "tests.*"]),
    python_requires=">=3.10",
    install_requires=[
        "tb-pe-client>=4.3.1,<4.4",
    ],
    entry_points={
        "console_scripts": [
            "synctb=synctb.cli:main",
        ],
    },
)
