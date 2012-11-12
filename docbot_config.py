
# jids which are authorized to manually push commands go here
authorized = []

projects = [
    Project.declare("pyengine",
        BuildAndMove(
            "devel docs",
            branch="devel",
            submodules=[
                "utils/pyLR1",
                "CEngine/Contrib/BinPack"
            ],
            commands=[
                ["cmake", "."],
                ["make", "docs-html"]
            ],
            move_from="{builddir}/docs/sphinx/build/html",
            move_to="/var/www/docroot/horazont/experimental/buildbot"
        ),
        repository_url="ssh://git.sotecware.net/PythonicEngine",
        pubsub_name="PythonicEngine",
        working_copy="/tmp/buildbot/PythonicEngine"
    ),
]
