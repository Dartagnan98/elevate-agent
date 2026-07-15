"""CLI-specific regression fixtures."""

from io import StringIO

import pytest
from prompt_toolkit.application import get_app_session
from prompt_toolkit.output import create_output


@pytest.fixture
def closed_prompt_toolkit_output():
    """Model a prior capture owner closing prompt_toolkit's cached stdout.

    prompt_toolkit's process-global ``AppSession`` lazily caches its first
    output.  pytest capture replaces and later closes stdout, so order/xdist
    tests need to prove CLI display helpers do not reuse that stale stream.
    """
    session = get_app_session()
    original_output = session._output
    stale_stdout = StringIO()
    session._output = create_output(stdout=stale_stdout)
    stale_stdout.close()
    try:
        yield
    finally:
        session._output = original_output
