from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="multisocks",
    version="1.0.0",
    author="tboy1337",
    author_email="obywhuie@anonaddy.com",
    description="A SOCKS proxy that aggregates multiple remote SOCKS proxies",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/tboy1337/multisocks",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Development Status :: 4 - Beta",
        "Topic :: Internet :: Proxy Servers",
        "Topic :: System :: Networking",
    ],
    python_requires=">=3.7",
    install_requires=[
        "asyncio",
        "python-socks",
        "aiohttp",
        "colorama",
        "typing_extensions",
        "pysocks"
    ],
    entry_points={
        "console_scripts": [
            "multisocks=multisocks.cli:main",
        ],
    },
) 