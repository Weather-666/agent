from fastapi import APIRouter

from app.api.v1.routers import (
    audit,
    auth,
    chat,
    credits,
    documents,
    expert_categories,
    expert_market,
    experts,
    featured_examples,
    knowledge_bases,
    knowledge_index,
    library,
    models,
    mcp_servers,
    ops,
    plan_market,
    plans,
    rbac,
    skills,
    storage,
    tenants,
    users,
)

api_router = APIRouter()
api_router.include_router(audit.router, prefix="/audit-events", tags=["audit-events"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(tenants.router, prefix="/tenants", tags=["tenants"])
api_router.include_router(credits.tenant_router, prefix="/tenants", tags=["credits"])
api_router.include_router(credits.router, prefix="/credits", tags=["credits"])
api_router.include_router(
    expert_categories.router,
    prefix="/expert-categories",
    tags=["expert-categories"],
)
api_router.include_router(experts.router, prefix="/experts", tags=["experts"])
api_router.include_router(
    expert_market.router,
    prefix="/expert-market",
    tags=["expert-market"],
)
api_router.include_router(
    featured_examples.category_router,
    prefix="/featured-categories",
    tags=["featured-categories"],
)
api_router.include_router(
    featured_examples.router,
    prefix="/featured-examples",
    tags=["featured-examples"],
)
api_router.include_router(
    featured_examples.market_router,
    prefix="/featured-market",
    tags=["featured-market"],
)
api_router.include_router(plans.router, prefix="/plans", tags=["plans"])
api_router.include_router(
    plan_market.router,
    prefix="/plan-market",
    tags=["plan-market"],
)
api_router.include_router(rbac.router, prefix="/rbac", tags=["rbac"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(
    mcp_servers.router,
    prefix="/mcp-connectors",
    tags=["mcp-connectors"],
)
api_router.include_router(ops.router, prefix="/ops", tags=["ops"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(library.router, prefix="/library", tags=["library"])
api_router.include_router(knowledge_bases.router, prefix="/knowledge-bases", tags=["knowledge-bases"])
# Documents and index review are nested under a knowledge base; there are no top-level routes.
api_router.include_router(
    documents.router,
    prefix="/knowledge-bases/{knowledge_base_id}/docs",
    tags=["docs"],
)
api_router.include_router(
    knowledge_index.router,
    prefix="/knowledge-bases/{knowledge_base_id}",
    tags=["knowledge-index"],
)
api_router.include_router(skills.router, prefix="/skills", tags=["skills"])
api_router.include_router(storage.router, prefix="/storage", tags=["storage"])
