"""Shared pytest fixtures for the wrapper + manager suites."""

import logging

import pytest


@pytest.fixture(autouse=True)
def _preserve_root_logging():
    """Stop CLI tests from breaking ``caplog`` in later tests.

    The CLI's ``_setup_logging`` calls ``logging.basicConfig(force=True)``, which
    removes ALL root-logger handlers — including pytest's caplog handler. A CLI
    test earlier in collection order then silently disables log capture for later
    tests (and collection order differs by platform, so it only bites on some
    OSes). Snapshot and restore the root handlers/level around every test, and
    clear any leaked ``logging.disable``, so captures stay deterministic.
    """
    root = logging.getLogger()
    cb = logging.getLogger("cloakbrowser")
    saved_handlers = root.handlers[:]
    saved_root_level = root.level
    saved_cb_level, saved_cb_prop = cb.level, cb.propagate
    logging.disable(logging.NOTSET)
    try:
        yield
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_root_level)
        cb.setLevel(saved_cb_level)
        cb.propagate = saved_cb_prop
        logging.disable(logging.NOTSET)


@pytest.fixture
def cloak_logs():
    """Capture 'cloakbrowser' log records via a dedicated handler on that logger.

    Robust where pytest's ``caplog`` is not: it doesn't depend on root handlers or
    propagation, so a prior test's ``basicConfig(force=True)`` / logger-level leak
    can't silently swallow the records (which flaked on Windows by collection order).
    Yields the list of ``LogRecord``s emitted during the test.
    """
    logger = logging.getLogger("cloakbrowser")
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    prev_level, prev_disabled = logger.level, logger.disabled
    logger.setLevel(logging.DEBUG)
    logger.disabled = False
    logging.disable(logging.NOTSET)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
        logger.disabled = prev_disabled
