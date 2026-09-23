from __future__ import annotations

from features.web.application.use_cases.web_fetch import WebFetchUseCase
from features.web.application.use_cases.web_search import WebSearchUseCase
from features.web.infrastructure.adapters.web_fetch_authorization import (
    WebFetchAuthorizationAdapter,
)
from features.web.infrastructure.adapters.web_search_authorization import (
    WebSearchAuthorizationAdapter,
)
from features.web.infrastructure.adapters.web_tools_fetch_runner import (
    WebToolsFetchRunnerAdapter,
)
from features.web.infrastructure.adapters.web_tools_search_runner import (
    WebToolsSearchRunnerAdapter,
)
from features.web.interfaces.controllers.web_fetch_controller import (
    WebFetchController,
)
from features.web.interfaces.controllers.web_search_controller import (
    WebSearchController,
)


def build_web_search_controller() -> WebSearchController:
    """Build the web_search controller with its default adapters."""
    authorization = WebSearchAuthorizationAdapter()
    runner = WebToolsSearchRunnerAdapter()
    use_case = WebSearchUseCase(
        authorization=authorization,
        runner=runner,
    )
    return WebSearchController(use_case)


def build_web_fetch_controller() -> WebFetchController:
    """Build the web_fetch controller with its default adapters."""
    authorization = WebFetchAuthorizationAdapter()
    runner = WebToolsFetchRunnerAdapter()
    use_case = WebFetchUseCase(
        authorization=authorization,
        runner=runner,
    )
    return WebFetchController(use_case)
