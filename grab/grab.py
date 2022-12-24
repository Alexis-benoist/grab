from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from copy import copy
from http.cookiejar import CookieJar
from pprint import pprint  # pylint: disable=unused-import
from secrets import SystemRandom
from typing import Any, cast, overload
from urllib.parse import urljoin, urlsplit

from .base import BaseGrab, BaseTransport
from .document import Document
from .errors import GrabMisuseError, GrabTooManyRedirectsError
from .request import Request
from .transport import Urllib3Transport
from .types import resolve_grab_entity, resolve_transport_entity
from .util.cookies import build_jar, create_cookie

__all__ = ["Grab", "request"]
logger = logging.getLogger(__name__)
logger_network = logging.getLogger("grab.network")
system_random = SystemRandom()


def copy_config(config: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """Copy grab config with correct handling of mutable config values."""
    return {x: copy(y) for x, y in config.items()}


def default_grab_config() -> MutableMapping[str, Any]:
    return {
        "reuse_cookies": True,
    }


class Grab(BaseGrab):
    __slots__ = ("config", "transport", "cookies")
    document_class: type[Document] = Document
    transport_class = Urllib3Transport

    def __init__(
        self,
        transport: None | BaseTransport | type[BaseTransport] = None,
        **kwargs: Any,
    ) -> None:
        self.config: MutableMapping[str, Any] = default_grab_config()
        self.transport = resolve_transport_entity(transport, self.transport_class)
        self.cookies = CookieJar()
        if kwargs:
            self.setup(**kwargs)

    def clone(self, **kwargs: Any) -> Grab:
        grab = Grab(transport=self.transport)
        grab.config = copy_config(self.config)
        grab.cookies = build_jar(list(self.cookies))  # building again makes a copy
        if kwargs:
            grab.setup(**kwargs)
        return grab

    def setup(self, **kwargs: Any) -> None:
        """Set up Grab instance configuration."""
        for key, val in kwargs.items():
            if key in self.config:
                self.config[key] = val
            else:
                raise GrabMisuseError("Unknown option: %s" % key)

    def merge_request_configs(
        self, request_config: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        cfg: MutableMapping[str, Any] = {}
        for key, val in request_config.items():
            if key not in Request.init_keys:
                raise GrabMisuseError("Invalid request parameter: {}".format(key))
            cfg[key] = val
        for key in Request.init_keys:
            if key not in cfg:
                cfg[key] = None
        return cfg

    def prepare_request(self, request_config: MutableMapping[str, Any]) -> Request:
        """Configure all things to make real network request.

        This method is called before doing real request via transport extension.
        """
        self.transport.reset()
        cfg = self.merge_request_configs(request_config)
        # REASONABLE DEFAULTS
        if cfg["url"] is None:
            raise GrabMisuseError("Request URL must be set")
        if not cfg["method"]:
            cfg["method"] = "GET"
        if cfg["follow_location"] is None:
            cfg["follow_location"] = True
        req = Request.create_from_mapping(cfg)
        # COOKIES EXTENSION
        self.update_session_cookies(req.cookies, req.url)
        return req

    def update_session_cookies(
        self, cookies: Mapping[str, Any], request_url: str
    ) -> None:
        request_host = urlsplit(request_url).hostname
        if request_host and cookies:
            # If cookie item is provided in form with no domain specified,
            # then use domain value extracted from request URL
            for name, value in cookies.items():
                self.cookies.set_cookie(
                    create_cookie(name=name, value=value, domain=request_host)
                )

    def log_request(self, req: Request) -> None:
        """Log request details via logging system."""
        proxy_info = (
            " via proxy {}://{}{}".format(
                req.proxy_type, req.proxy, " with auth" if req.proxy_userpwd else ""
            )
            if req.proxy
            else ""
        )
        logger_network.debug("%s %s%s", req.method or "GET", req.url, proxy_info)

    def find_redirect_url(self, doc: Document) -> None | str:
        assert doc.headers is not None
        if doc.code in {301, 302, 303, 307, 308} and doc.headers["Location"]:
            return cast(str, doc.headers["Location"])
        return None

    @overload
    def request(self, url: Request, **request_kwargs: Any) -> Document:
        ...

    @overload
    def request(self, url: None | str = None, **request_kwargs: Any) -> Document:
        ...

    def request(
        self, url: None | str | Request = None, **request_kwargs: Any
    ) -> Document:
        if isinstance(url, Request):
            req = url
        else:
            if url is not None:
                request_kwargs["url"] = url
            req = self.prepare_request(request_kwargs)
        redir_count = 0
        while True:
            self.log_request(req)
            self.transport.request(req, self.cookies)
            with self.transport.wrap_transport_error():
                doc = self.process_request_result(req)
            if (
                req.follow_location
                and (redir_url := self.find_redirect_url(doc)) is not None
            ):
                redir_count += 1
                if redir_count > req.redirect_limit:
                    raise GrabTooManyRedirectsError()
                redir_url = urljoin(req.url, redir_url)
                request_kwargs["url"] = redir_url
                req = self.prepare_request(request_kwargs)
                continue
            return doc

    def submit(self, doc: Document, **kwargs: Any) -> Document:
        return self.request(Request(**doc.get_form_request(**kwargs)))

    def process_request_result(self, req: Request) -> Document:
        """Process result of real request performed via transport extension."""
        doc = self.transport.prepare_response(req, document_class=self.document_class)
        if self.config["reuse_cookies"]:
            for item in doc.cookies:
                self.cookies.set_cookie(item)
        return doc

    def clear_cookies(self) -> None:
        """Clear all remembered cookies."""
        self.cookies.clear()

    def __getstate__(self) -> MutableMapping[str, Any]:
        state = {}
        for slot_name in self.__slots__:
            if slot_name == "cookies":
                state["_cookies_items"] = list(self.cookies)
            else:
                state[slot_name] = getattr(self, slot_name)
        return state

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        for key, value in state.items():
            if key == "_cookies_items":
                self.cookies = build_jar(value)
            else:
                if key not in self.__slots__:
                    raise ValueError("Key '{}' is not in __slots__'".format(key))
                setattr(self, key, value)


def request(
    url: None | str | Request = None,
    grab: None | BaseGrab | type[BaseGrab] = None,
    **request_kwargs: Any,
) -> Document:
    grab = resolve_grab_entity(grab, default=Grab)
    return grab.request(url, **request_kwargs)
