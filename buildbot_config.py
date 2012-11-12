
# jids which are authorized to manually push commands go here
authorized = []

projects = [
    # declare a project
    Project.declare(

        # first the projects name. this is used in channel output
        "pyengine",

        # Then an arbitrary amount of build targets. Anything inheriting from
        # Execute can go here.
        BuildAndMove(
            # display name again
            "devel docs",

            # branch to trigger on for pubsub (defaults to "master")
            branch="devel",

            # submodules which have to be inited and updated
            submodules=[
                "utils/pyLR1",
                "CEngine/Contrib/BinPack"
            ],

            # commands to execute for a complete build
            commands=[
                ["cmake", "."],
                ["make", "docs-html"]
            ],

            # these are special to BuildAndMove and indicate from where to where
            # data shall be moved after a successful build. Can only execute
            # one move operation. {builddir} will be substituted with the
            # directory into which the repository has been cloned
            move_from="{builddir}/docs/sphinx/build/html",
            move_to="/var/www/docroot/horazont/experimental/buildbot"
        ),

        # this is needed by and Build descendant
        repository_url="ssh://git.sotecware.net/PythonicEngine",

        # the repositories name on the pubsub node
        pubsub_name="PythonicEngine",

        # directory where to clone the repository to. If this is omitted, a new
        # clone is always created at a temporary location (see python3's
        # tempfile module)
        working_copy="/tmp/buildbot/PythonicEngine"
    ),
    Project.declare(
        # display name once more
        "zombofant.net",

        # trigger and execute a proper git pull --rebase operation on an
        # repository
        Pull(
            # you guess it
            "served instance",

            # location of an existing(!) clone of the git repository where the
            # working directory will be moved to
            "/var/www/net/zombofant/root",

            # branch to trigger on -- no git checkout will take place though!
            branch="master",

            # branch to pull from. this must be a tuple naming the git remote
            # and the branch or just None if you want git to figure it out
            remote_location=("origin", "master"),

            # these commands are run after a successful pull
            after_pull_commands=[
                ["touch", "site/sitemap.xml"]
            ]
        ),
        # see above
        pubsub_name="zombofant.net"
    ),
]
