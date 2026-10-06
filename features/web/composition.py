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
from features.web.application.use_cases.browse_page import BrowsePageUseCase
from features.web.application.use_cases.browser_fill import BrowserFillUseCase
from features.web.application.use_cases.browser_submit import BrowserSubmitUseCase
from features.web.infrastructure.adapters.browser_authorization import (
    BrowserAuthorizationAdapter,
)
from features.web.infrastructure.adapters.playwright_runner import (
    PlaywrightRunnerAdapter,
)
from features.web.interfaces.controllers.browse_page_controller import (
    BrowsePageController,
)
from features.web.interfaces.controllers.browser_fill_controller import (
    BrowserFillController,
)
from features.web.interfaces.controllers.browser_submit_controller import (
    BrowserSubmitController,
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


# Module-level singleton: all browser controllers share one runner so that
# browser_fill -> browser_submit reuse the same Playwright session.
_SHARED_BROWSER_RUNNER = None


def _build_browser_stack():
    """Shared authorization + runner for browser tools."""
    global _SHARED_BROWSER_RUNNER
    authorization = BrowserAuthorizationAdapter()
    if _SHARED_BROWSER_RUNNER is None:
        _SHARED_BROWSER_RUNNER = PlaywrightRunnerAdapter()
    return authorization, _SHARED_BROWSER_RUNNER


def build_browse_page_controller() -> BrowsePageController:
    """Build the browse_page controller (read level)."""
    authorization, runner = _build_browser_stack()
    use_case = BrowsePageUseCase(
        authorization=authorization,
        runner=runner,
    )
    return BrowsePageController(use_case)


def build_browser_fill_controller() -> BrowserFillController:
    """Build the browser_fill controller (execute level)."""
    authorization, runner = _build_browser_stack()
    use_case = BrowserFillUseCase(
        authorization=authorization,
        runner=runner,
    )
    return BrowserFillController(use_case)


def build_browser_submit_controller() -> BrowserSubmitController:
    """Build the browser_submit controller (destructive level)."""
    authorization, runner = _build_browser_stack()
    use_case = BrowserSubmitUseCase(
        authorization=authorization,
        runner=runner,
    )
    return BrowserSubmitController(use_case)
