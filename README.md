xmpp-crowd
==========

This is just a bunch of bots based on the great [SleekXMPP][1] python library,
which are running on my system to make my life a little bit easier. Some of
these will not be of any use for the broader public, especially as they're
missing docstrings (*ahem*), but if anyone can get any interest out of them,
it's fine.

`hub.py`
--------

`hub.py` is in fact the core of the “modern” bots (i.e. all but `foobot.py`),
which abstracts away some of the (very little) boilerplate all bots share.


`buildbot.py`
-------------

Thats a really cool guy who does what you'd suspect from reading his name.
He'll listen for events on a pubsub node and trigger shell commands or whatever
when certain events come in. It's built to work together with ``gitbot.py``,
which will push the proper events if installed in a git repositories
``post-update`` hook. It should be easy to customize both to work with ``hg``
or similar.

``buildbot`` is highly configurable. See the ``buildbot_config.py`` for a
nicely commented example.

   [1]: https://github.com/fritzy/SleekXMPP
