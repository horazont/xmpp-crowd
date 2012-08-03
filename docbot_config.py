
# jids which are authorized to manually push commands go here
authorized = []

projects = [
    Project.declare(
        # project name
        "pyengine",  

        # arbitary number of Branch() objects, which specify parameters to build
        # docs for the respective branch. Omit if you don't want to build docs
        # for a branch
        Branch(
            # branch name in git
            "devel",
            # path to move the docs to
            "/var/www/net/zombofant/pyengine/docs",
            # command to build the docs (note the hidden kwarg cmake!)
            ["make", "docs-html"],
            # git submodules which are needed
            submodules=["utils/pyLR1", "CEngine/Contrib/BinPack"]
        ),
        # path to clone the repo to
        checkoutPath="/tmp/docbot/docs-PythonicEngine",
        # url to clone the source from
        cloneSource="ssh://git.sotecware.net/PythonicEngine.git",
        # optional list of tuples to react on in the git pubsub feed, tuples
        # consist of repository name and branch which got pushed
        triggers=[
            ("PythonicEngine", "devel")
        ]
    ),
]
