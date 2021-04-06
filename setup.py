from setuptools import setup

setup(
    name="deadstream",
    version="0.0.1",
    packages=["GD"],
    install_requires=[
        'aiohttp',
        'requests',
        'python-mpv',
        'pickle5'
    ],
    package_data={
        "deadstream": ["FreeMono.ttf", "set_breaks.csv"]
    }
)
