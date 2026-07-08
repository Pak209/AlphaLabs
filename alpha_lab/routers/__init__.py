"""API routers extracted from api.create_app (Phase 2 PR4+).

Each module exposes a build_<name>_router(lab) factory returning an APIRouter
whose handlers capture the SAME service instance create_app holds — identical
closure semantics to the original inline handlers, declared in another file.
App-level middleware (auth) applies to included routers unchanged.
"""
