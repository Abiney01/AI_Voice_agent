from typing import List
from fastapi import APIRouter, HTTPException, Path
from app.schemas.order import OrderCreate, OrderItemAdd, OrderOut
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderOut, summary="Create a new order session")
async def create_order(data: OrderCreate):
    service = OrderService()
    order = await service.get_or_create_active_order(data.customer_id)
    return _build_order_out(order)


@router.get("/{order_id}", response_model=OrderOut, summary="Get order details")
async def get_order(order_id: int):
    service = OrderService()
    order = await service.get_order(order_id)
    return _build_order_out(order)


@router.post("/{order_id}/items", response_model=OrderOut, summary="Add item to order")
async def add_item(
    order_id: int,
    data: OrderItemAdd,
):
    service = OrderService()
    order = await service.add_item(order_id, data)
    return _build_order_out(order)


@router.delete("/{order_id}/items/{item_id}", response_model=OrderOut, summary="Remove item from order")
async def remove_item(
    order_id: int = Path(...),
    item_id: int = Path(...),
):
    service = OrderService()
    order = await service.remove_item(order_id, item_id)
    return _build_order_out(order)


@router.put("/{order_id}/confirm", response_model=OrderOut, summary="Confirm order")
async def confirm_order(order_id: int):
    service = OrderService()
    order = await service.confirm_order(order_id)
    return _build_order_out(order)


@router.put("/{order_id}/cancel", response_model=OrderOut, summary="Cancel order")
async def cancel_order(order_id: int):
    service = OrderService()
    order = await service.cancel_order(order_id)
    return _build_order_out(order)


@router.get("/customer/{customer_id}", response_model=List[OrderOut], summary="Get customer order history")
async def get_customer_orders(customer_id: int):
    service = OrderService()
    orders = await service.get_customer_history(customer_id)
    return [_build_order_out(o) for o in orders]


def _build_order_out(order) -> OrderOut:
    """Build OrderOut with computed item names and subtotals."""
    from app.schemas.order import OrderItemOut

    items_out = []
    # In Prisma, order.items is a list of OrderItem model instances
    if order.items:
        for item in order.items:
            subtotal = float(item.unit_price) * item.quantity
            items_out.append(
                OrderItemOut(
                    id=item.id,
                    menu_item_id=item.menu_item_id,
                    menu_item_name=item.menu_item.name if item.menu_item else "",
                    quantity=item.quantity,
                    unit_price=float(item.unit_price),
                    customization_notes=item.customization_notes,
                    subtotal=subtotal,
                )
            )

    return OrderOut(
        id=order.id,
        customer_id=order.customer_id,
        status=order.status,
        total_amount=float(order.total_amount),
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=items_out,
    )
