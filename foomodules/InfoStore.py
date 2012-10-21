import shlex
import pickle

import foomodules.Base as Base
import foomodules.URLLookup as URLLookup

class Nugget(object):
    def __init__(self, name, contents, keywords=[]):
        self.name = name
        self.contents = contents
        self.keywords = set(keywords)

class Store(object):
    def __init__(self, data_filename,
            url_lookup=None,
            min_keyword_length=3,
            min_name_length=3,
            min_info_length=10,
            max_keyword_count=2048,
            max_info_count=2048,
            max_info_length=2048,
            max_keyword_length=64,
            max_name_length=64):
        self.keywords = {}
        self.names = {}
        self.url_lookup = url_lookup
        self.data_filename = data_filename
        self.min_name_length = int(min_name_length)
        self.min_keyword_length = int(min_keyword_length)
        self.min_info_length = int(min_info_length)
        self.max_keyword_count = int(max_keyword_count)
        self.max_info_count = int(max_info_count)
        self.max_info_length = int(max_info_length)
        self.max_name_length = int(max_name_length)
        self.max_keyword_length = int(max_keyword_length)

        self.try_load()

    def _check_keywords(self, keywords):
        if self.min_keyword_length <= 0 and self.max_keyword_length <= 0:
            return
        for kw in keywords:
            if len(kw) < self.min_keyword_length:
                raise ValueError("Keywords have to have a minimum length of {0:d}".format(self.min_keyword_length))
            if self.max_keyword_length > 0 and len(kw) > self.max_keyword_length:
                raise ValueError("Keywords have to have a maximum length of {0:d}".format(self.max_keyword_length))

    def _check_name(self, name):
        if len(name) < self.min_name_length:
            raise ValueError("Names have to have a minimum length of {0:d}".format(self.min_name_length))
        if self.max_name_length > 0 and len(name) > self.max_name_length:
            raise ValueError("Names have to have a maximum length of {0:d}".format(self.max_name_length))

    def _check_contents(self, contents):
        if len(contents) < self.min_info_length:
            raise ValueError("Information have to have a minimum length of {0:d}".format(self.min_info_length))
        if self.max_info_length > 0 and len(contents) > self.max_info_length:
            raise ValueError("Information have to have a maximum length of {0:d}".format(self.min_info_length))

    def _check_limits(self):
        if (self.max_keyword_count > 0 and len(self.keywords) > self.max_keyword_count) or \
           (self.max_info_count > 0 and len(self.names) > self.max_info_count):
            raise ValueError("Sorry, I cannot memorize more. You must allow me to forget something else first.")

    def try_load(self):
        try:
            f = open(self.data_filename, "rb")
        except IOError:
            return
        with f:
            self.load(f)

    def load(self, filelike):
        self.keywords, self.names = pickle.load(filelike)

    def save(self):
        with open(self.data_filename, "wb") as f:
            pickle.dump((self.keywords, self.names), f)

    def store_info(self, name, contents, keywords=[]):
        self._check_limits()
        self._check_name(name)
        self._check_contents(contents)
        self._check_keywords(keywords)
        if name in self.names:
            raise KeyError(name)
        info = Nugget(name, contents, keywords=keywords)
        self.names[name] = info
        for keyword in keywords:
            self.keywords.setdefault(keyword, set()).add(info)

    def delete_info(self, info):
        self.remove_keywords(info, info.keywords)
        del self.names[info.name]

    def find_by_keywords(self, keywords):
        matches = None
        for kw in keywords:
            try:
                this_match = self.keywords[kw]
            except KeyError:
                return []
            if matches is None:
                matches = set(this_match)
            else:
                matches &= this_match
        return matches

    def attach_keywords(self, info, keywords):
        if not keywords:
            return
        self._check_limits()
        for keyword in keywords:
            self.keywords.setdefault(keyword, set()).add(info)
        info.keywords |= set(keywords)

    def remove_keywords(self, info, keywords):
        for keyword in keywords:
            try:
                infoset = self.keywords[keyword]
            except KeyError:
                # odd, but ignore
                pass
            infoset.remove(info)
            if not infoset:
                del self.keywords[keyword]
        info.keywords -= set(keywords)

    def rename_keyword(self, oldname, newname):
        infoset = self.keywords[oldname]
        del self.keywords[oldname]
        for info in infoset:
            info.keywords.remove(oldname)
            info.keywords.add(newname)
        self.keywords[newname] = infoset

    def rename_info(self, oldname, newname):
        info = self.names[oldname]
        del self.names[oldname]
        info.name = newname
        self.names[newname] = info


class StoreCommand(Base.ArgparseCommand):
    def __init__(self, store, command_name="store", **kwargs):
        super().__init__(command_name, **kwargs)
        self.store = store
        self.argparse.add_argument(
            "-k", "--keyword", "--tag", "-t",
            dest="tags",
            action="append",
            help="Attach some tags to the information."
        )
        self.argparse.add_argument(
            "name",
            help="Descriptive name of the information to store"
        )
        self.argparse.add_argument(
            "contents",
            help="Contents of the information. If this is (only) a URL, it will be url-lookup'd upon retrieval"
        )

    def _call(self, msg, args, errorSink=None):
        try:
            self.store.store_info(args.name, args.contents, keywords=(args.tags or []))
        except ValueError as err:
            self.reply(msg, "Sorry, {0}".format(err))
        except KeyError as err:
            self.reply(msg, "Sorry, that name is already assigned".format(err))

class ExistingCommandBase(Base.ArgparseCommand):
    def _get_or_reply(self, msg, name):
        try:
            info = self.store.names[name]
        except KeyError:
            self.reply(msg, "Unknown information: {0}".format(name))
            return None
        return info

class AmendCommand(ExistingCommandBase):
    def __init__(self, store, command_name="amend", **kwargs):
        super().__init__(command_name, **kwargs)
        self.store = store
        self.argparse.add_argument(
            "-a", "--add",
            dest="add",
            default=[],
            action="append",
            help="Tags to attach to the information."
        )
        self.argparse.add_argument(
            "-r", "--remove", "--rm",
            dest="remove",
            default=[],
            action="append",
            help="Tags to remove from the information."
        )
        self.argparse.add_argument(
            "name",
            help="Name of the information to amend."
        )

    def _call(self, msg, args, errorSink=None):
        if not args.add and not args.remove:
            return
        info = self._get_or_reply(msg, args.name)
        if info is None:
            return
        self.store.attach_keywords(info, args.add)
        self.store.remove_keywords(info, args.remove)

class RemoveCommand(ExistingCommandBase):
    def __init__(self, store, command_name="rm", **kwargs):
        super().__init__(command_name, **kwargs)
        self.store = store
        self.argparse.add_argument(
            "name",
            nargs="+",
            help="Name of the information to amend."
        )

    def _call(self, msg, args, errorSink=None):
        unknown = set()
        for name in args.name:
            info = self.store.names.get(name, None)
            if info is None:
                unknown.add(name)
                continue
            self.store.delete_info(info)
        if len(unknown) > 0:
            self.reply(msg, "Could not remove the following (unknown) information: {0}".format(", ".join(unknown)))

class RenameCommand(ExistingCommandBase):
    def __init__(self, store, command_name="mv", **kwargs):
        super().__init__(command_name, **kwargs)
        self.store = store
        self.argparse.add_argument(
            "-t", "--tag", "-k", "--keyword",
            dest="keyword",
            action="store_true",
            default=False,
            help="Rename a keyword instead of an information. When doing this, the keyword will be completely renamed, i.e. information accessible by the old keyword will be accessible by the new keyword."
        )
        self.argparse.add_argument(
            "oldname",
            help="Current name of the information or tag to move"
        )
        self.argparse.add_argument(
            "newname",
            help="New name for the information or tag to move"
        )

    def _call(self, msg, args, errorSink=None):
        if info.keyword:
            try:
                self.store.rename_keyword(args.oldname, args.newname)
            except KeyError:
                return
        else:
            try:
                self.store.rename_info(args.oldname, args.newname)
            except KeyError:
                return

class ListCommand(Base.ArgparseCommand):
    def __init__(self, store, command_name="list", **kwargs):
        super().__init__(command_name, **kwargs)
        self.store = store
        self.choices = {"keyword": self._keywords, "kw": self._keywords, "keywords": self._keywords, "info": self._info}
        self.argparse.add_argument(
            "what",
            choices=self.choices,
            help="What to list"
        )

    def _keywords(self, msg, args):
        keywords = self.store.keywords.keys()
        if len(keywords) == 0:
            self.reply(msg, "Sorry, I don't know any keywords. Teach me some with !amend or !store.")
            return
        self.reply(msg, "I know something about these keywords: {0}".format(", ".join(sorted(keywords))))

    def _info(self, msg, args):
        names = self.store.names.keys()
        if len(names) == 0:
            self.reply(msg, "Sorry, I don't know any names. Teach me some with !store.")
            return
        self.reply(msg, "Stored information: {0}".format(", ".join(sorted(names))))

    def _call(self, msg, args, errorSink=None):
        self.choices[args.what](msg, args)

class SaveCommand(Base.MessageHandler):
    def __init__(self, store):
        super().__init__()
        self.store = store

    def __call__(self, msg, arguments, errorSink=None):
        if arguments.strip():
            return
        self.store.save()
        self.reply(msg, "Successfully stored information.")

class KeywordListener(Base.PrefixListener):
    def __init__(self, store, prefix="+", **kwargs):
        super().__init__(prefix, **kwargs)
        self.prefix = prefix
        self.store = store

    def _match(self, info, msg):
        contents = info.contents
        if self.store.url_lookup:
            url_lookup = self.store.url_lookup
            m = url_lookup.urlRE.match(contents)
            if m:
                url = m.group(0)
                try:
                    iterable = iter(url_lookup.processURL(url))
                    try:
                        first_line = next(iterable)
                    except StopIteration:
                        return
                except URLLookup.URLLookupError as err:
                    first_line = "sorry, I could not look that up: {0}".format(str(err))
                    iterable = iter([])
                self.reply(msg, "{0}: {1} – {2}".format(
                    info.name,
                    contents,
                    first_line
                ))
                for line in iterable:
                    self.reply(msg, line)
                return

        self.reply(msg, "{0}: {1}".format(info.name, contents))

    def _multi_match(self, matches, msg):
        self.reply(msg, "Found {0} possible matches".format(len(matches)))
        for match in sorted(matches, key=lambda m: m.name):
            self.reply(msg, "{0}: {1}".format(match.name, match.contents))

    def _prefix_matched(self, msg, contents, errorSink=None):
        keywords = [kw for kw in (kw.strip() for kw in shlex.split(contents)) if kw]
        if len(keywords) == 1:
            # also try a search for a name
            name = keywords[0]
            try:
                self._match(self.store.names[name], msg)
            except KeyError:
                pass
            else:
                return
        if len(keywords) == 0:
            return

        matches = self.store.find_by_keywords(keywords)
        if not matches:
            return

        if len(matches) == 1:
            self._match(next(iter(matches)), msg)
            return
        else:
            self._multi_match(matches, msg)


