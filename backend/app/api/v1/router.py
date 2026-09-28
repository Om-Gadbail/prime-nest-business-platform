"""Versioned API router: all /api/v1 routes are assembled here."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    ai,
    ai_chat,
    approvals,
    attendance,
    audit,
    auth,
    automation,
    bookings,
    business,
    communications,
    contacts,
    customers,
    dashboard,
    domain_events,
    growth_analytics,
    identity,
    integrations,
    leads,
    members,
    memberships,
    notifications,
    owner,
    payments,
    public,
    seats,
    system,
    tasks,
    whatsapp,
)

router = APIRouter()
router.include_router(system.router)
router.include_router(auth.router)
router.include_router(business.router)
router.include_router(leads.router)
router.include_router(bookings.router)
router.include_router(contacts.router)
router.include_router(customers.router)
router.include_router(notifications.router)
router.include_router(public.router)
router.include_router(ai.router)
router.include_router(tasks.router)
router.include_router(audit.router)
router.include_router(domain_events.router)
router.include_router(dashboard.router)
router.include_router(identity.router)
router.include_router(members.router)
router.include_router(memberships.router)
router.include_router(payments.router)
router.include_router(attendance.router)
router.include_router(seats.router)
router.include_router(approvals.router)
router.include_router(owner.router)
router.include_router(automation.router)
router.include_router(communications.router)
router.include_router(whatsapp.router)
router.include_router(integrations.router)
router.include_router(ai_chat.router)
router.include_router(growth_analytics.growth_router)
router.include_router(growth_analytics.analytics_router)
router.include_router(growth_analytics.brief_router)
