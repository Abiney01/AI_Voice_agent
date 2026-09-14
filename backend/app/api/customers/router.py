from fastapi import APIRouter, HTTPException
from app.schemas.customer import (
    CustomerIdentify,
    CustomerOut,
    CustomerPreferencesUpdate,
    CustomerProfile,
)
from app.services.customer_service import CustomerService
from app.services.order_service import OrderService

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("/identify", response_model=CustomerOut, summary="Register or identify a customer by phone number")
async def identify_customer(data: CustomerIdentify):
    service = CustomerService()
    customer, is_returning = await service.identify(data)

    # Cancel any leftover active order from a previous session so the new conversation starts fresh
    order_svc = OrderService()
    try:
        active_order = await order_svc.order_repo.get_active_order(customer.id)
        if active_order:
            await order_svc.cancel_order(active_order.id)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to cancel previous active order for customer {customer.id} on identify: {e}")

    out = CustomerOut.model_validate(customer)
    out.is_returning = is_returning
    return out


@router.get("/{customer_id}", response_model=CustomerProfile, summary="Get customer profile")
async def get_customer(customer_id: int):
    service = CustomerService()
    customer = await service.get_profile(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Enrich with order stats
    order_svc = OrderService()
    orders = await order_svc.get_customer_history(customer_id, limit=100)

    profile = CustomerProfile.model_validate(customer)
    profile.total_orders = len(orders)
    if orders:
        profile.last_order_date = orders[0].created_at
    return profile


@router.put("/{customer_id}/preferences", summary="Update customer preferences")
async def update_preferences(
    customer_id: int,
    data: CustomerPreferencesUpdate,
):
    service = CustomerService()
    customer = await service.get_profile(customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    prefs = await service.update_preferences(customer_id, data)
    return {"success": True, "preferences": prefs}
