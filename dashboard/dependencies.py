"""FastAPI ``Depends()`` accessors that pull services from request state.

Each accessor reads ``request.app.state.container`` (an ``AppContainer`` set
by ``dashboard.app_factory.build_app``) and returns the matching attribute.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from dashboard.app_container import AppContainer


def get_container(request: Request) -> "AppContainer":
    return request.app.state.container


def get_project_manager(request: Request) -> Any:
    return get_container(request).project_manager


def get_project_context(request: Request) -> Any:
    return get_container(request).project_context


def get_review_workflow(request: Request) -> Any:
    return get_container(request).review_workflow


def get_content_workflow(request: Request) -> Any:
    return get_container(request).content_workflow


def get_publishing_service(request: Request) -> Any:
    return get_container(request).publishing_service


def get_nostr_signing(request: Request) -> Any:
    return get_container(request).nostr_signing


def get_job_queue(request: Request) -> Any:
    return get_container(request).job_queue


def get_idea_lab(request: Request) -> Any:
    return get_container(request).idea_lab


def get_feedback_manager(request: Request) -> Any:
    return get_container(request).feedback_manager


def get_analytics(request: Request) -> Any:
    return get_container(request).analytics


def get_reasoning_tracker(request: Request) -> Any:
    return get_container(request).reasoning_tracker


def get_secret_service(request: Request) -> Any:
    return get_container(request).secret_service


def get_publishing_manager(request: Request) -> Any:
    return get_container(request).publishing_manager


def get_job_runner(request: Request) -> Any:
    return get_container(request).job_runner


def get_store(request: Request) -> Any:
    return get_container(request).store


def get_generator(request: Request) -> Any:
    return get_container(request).generator
