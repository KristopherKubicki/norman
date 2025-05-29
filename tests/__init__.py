"""Expose available test modules for discovery."""

# Only import tests that actually exist to avoid ImportError during test
# collection. Currently the connectors package only includes IRC and Slack
# tests.
from .connectors import test_irc, test_slack
from . import test_filters
