import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="rum_with_telegram",
    version="0.8.1",
    author="liujuanjuan1984",
    author_email="qiaoanlu@163.com",
    description="A bot, send telegram update to rum group as trx, and get new trx from rum group to channel.",
    keywords=["python-telegram-bot", "rumsystem", "quorum"],
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/liujuanjuan1984/rum_with_telegram",
    project_urls={
        "Github Repo": "https://github.com/liujuanjuan1984/rum_with_telegram",
        "Bug Tracker": "https://github.com/liujuanjuan1984/rum_with_telegram/issues",
        "About Quorum": "https://github.com/rumsystem/quorum",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    packages=setuptools.find_packages(exclude=["example"]),
    python_requires=">=3.7",
    install_requires=[
        "python-telegram-bot==20.2",
        "quorum-data-py",
        "quorum-mininode-py",
        "sqlalchemy",
        "eth-account==0.5.8",
    ],
)
