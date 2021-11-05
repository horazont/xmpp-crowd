import asyncio
import dataclasses
import enum
import logging
import urllib.parse
import time
import typing

import aiohttp

import aioxmpp.cache

import aiofoomodules.handlers

from aiofoomodules.utils import (
    get_simple_body,
)


logger = logging.getLogger(__name__)


class LookupKind(enum.Enum):
    MERGE_REQUEST = "merge_requests"
    ISSUE = "issues"


@dataclasses.dataclass(frozen=True)
class LookupRequest:
    project_ref: typing.Union[int, str]
    kind: LookupKind
    iid: int


class GitLabLookup(aiofoomodules.handlers.AbstractHandler):
    def __init__(
            self,
            finder,
            *,
            web_base="https://gitlab.com",
            api_base=None,
            recent_lookups=100,
            recent_timeout=120,
            lookup_timeout=10,
            negative_cache_ttl=3600,
            max_lookups_per_message=5):
        super().__init__()
        self.finder = finder
        self.web_base = web_base
        self.api_base = api_base or f"{web_base}/api/v4"
        self.lookup_timeout = lookup_timeout
        self.max_lookups_per_message = max_lookups_per_message
        self.recent_timeout = recent_timeout
        self.negative_cache_ttl = negative_cache_ttl
        self._recent = aioxmpp.cache.LRUDict()
        self._recent.maxsize = recent_lookups
        self._nonexistent_project_cache = aioxmpp.cache.LRUDict()
        self._nonexistent_project_cache.maxsize = 20
        self._project_id_cache = aioxmpp.cache.LRUDict()
        self._project_id_cache.maxsize = 1000
        self._project_reverse_cache = aioxmpp.cache.LRUDict()
        self._project_reverse_cache.maxsize = 1000

    def _api_url(self, path: str) -> str:
        result = f"{self.api_base}/{path}"
        logger.debug("generated API url: %r", result)
        return result

    async def _resolve_project(
            self,
            session: aiohttp.ClientSession,
            project_ref: typing.Union[str, int]) -> typing.Tuple[int, str]:
        now = time.monotonic()
        try:
            last_nxproject_timestamp = self._nonexistent_project_cache[
                project_ref
            ]
        except KeyError:
            pass
        else:
            if now - last_nxproject_timestamp < self.negative_cache_ttl:
                logger.debug("skipping recheck of project %r because there"
                             " is a negative cache entry from %d "
                             "(and now is %d)",
                             project_ref,
                             last_nxproject_timestamp,
                             now)
                raise LookupError("project does not exist")
            del self._nonexistent_project_cache[project_ref]

        def existence_check(resp):
            if resp.status == 404:
                self._nonexistent_project_cache[project_ref] = now
                raise LookupError("project does not exist")

        if isinstance(project_ref, int):
            try:
                return (project_ref, self._project_reverse_cache[project_ref])
            except KeyError:
                pass

            async with session.get(
                    self._api_url(f"projects/{project_ref}"),
                    ) as resp:
                existence_check(resp)
                resp.raise_for_status()
                result = await resp.json()
                logger.debug("resolved project by id %r: %r", project_ref,
                             result)
                project_name = result["path_with_namespace"]

            self._project_id_cache[project_name] = project_ref
            self._project_reverse_cache[project_ref] = project_name
            return project_ref, project_name

        try:
            return (self._project_id_cache[project_ref], project_ref)
        except KeyError:
            pass

        encoded_name = urllib.parse.quote(project_ref, safe="")
        async with session.get(
                self._api_url(f"projects/{encoded_name}"),
                ) as resp:
            existence_check(resp)
            resp.raise_for_status()
            result = await resp.json()
            logger.debug("resolved project by name %r: %r", encoded_name,
                         result)
            project_id = result["id"]

        self._project_id_cache[project_ref] = project_id
        self._project_reverse_cache[project_id] = project_ref
        return (project_id, project_ref)

    async def lookup_object(
            self,
            session: aiohttp.ClientSession,
            project_id: int,
            kind: LookupKind,
            iid: int) -> typing.Mapping:
        url = self._api_url(
            f"projects/{project_id}/{kind.value}/{iid}",
        )
        async with session.get(url) as resp:
            resp.raise_for_status()
            result = await resp.json()
            logger.debug("retrieved %s/%d as %r", kind.value, iid, result)
            return result

    def _format(self, req, project_name, object_):
        friendly_name = {
            LookupKind.MERGE_REQUEST: "MR",
            LookupKind.ISSUE: "issue",
        }[req.kind]
        return f"{project_name}: {object_['state']} {friendly_name} {object_['iid']}: {object_['title']} ({self.web_base}/{project_name}/-/{req.kind.value}/{object_['iid']})"

    async def process_requests(self, ctx, message, reqs):
        async with aiohttp.ClientSession() as session:
            lookups = []
            names = []
            final_reqs = []
            now = time.monotonic()
            for req in reqs:
                try:
                    recent_timestamp = self._recent[req]
                except KeyError:
                    pass
                else:
                    if now - recent_timestamp < self.recent_timeout:
                        logger.debug("skipping lookup %r because I did "
                                     "that recently (%d, now is %d)",
                                     req,
                                     recent_timestamp,
                                     now)
                        continue
                    del self._recent[req]

                try:
                    project_id, project_name = \
                        await self._resolve_project(session, req.project_ref)
                except LookupError:
                    logger.warning("skipping lookup %r because the project "
                                   "was not resolvable", req)
                    continue

                names.append(project_name)
                lookups.append(asyncio.create_task(self.lookup_object(
                    session,
                    project_id,
                    req.kind,
                    req.iid,
                )))
                final_reqs.append(req)

            if not lookups:
                return

            done, pending = await asyncio.wait(
                lookups,
                return_when=asyncio.ALL_COMPLETED,
                timeout=self.lookup_timeout,
            )
            for fut in pending:
                fut.cancel()

            for fut, name, req in zip(lookups, names, final_reqs):
                if fut.cancelled():
                    continue
                if fut.exception():
                    logger.error(
                        "failed to resolve %r: %s",
                        req, fut.exception(),
                    )
                    continue
                ctx.reply(self._format(req, name, fut.result()),
                          use_nick=False)
                self._recent[req] = now


    def analyse_message(self, ctx, message):
        body = get_simple_body(message)

        seen = set()
        reqs = []
        for req in self.finder(body):
            if req in seen:
                continue
            seen.add(req)
            reqs.append(req)

        if len(reqs) > self.max_lookups_per_message:
            return

        if reqs:
            yield self.process_requests(ctx, message, reqs)
