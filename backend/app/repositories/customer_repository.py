from typing import Optional
from app.core.prisma import prisma
from app.prisma_client.models import Customer, CustomerPreferences
from app.schemas.customer import CustomerPreferencesUpdate


class CustomerRepository:
    async def get_by_phone(self, phone_number: str) -> Optional[Customer]:
        return await prisma.customer.find_unique(
            where={"phone_number": phone_number},
            include={"preferences": True}
        )

    async def get_by_id(self, customer_id: int) -> Optional[Customer]:
        return await prisma.customer.find_unique(
            where={"id": customer_id},
            include={"preferences": True}
        )

    async def create(self, phone_number: str, name: Optional[str] = None) -> Customer:
        return await prisma.customer.create(
            data={
                "phone_number": phone_number,
                "name": name,
                "preferences": {
                    "create": {}
                }
            },
            include={"preferences": True}
        )

    async def update_name(self, customer: Customer, name: str) -> Customer:
        return await prisma.customer.update(
            where={"id": customer.id},
            data={"name": name},
            include={"preferences": True}
        )

    async def update_preferences(
        self, customer_id: int, data: CustomerPreferencesUpdate
    ) -> Optional[CustomerPreferences]:
        update_data = data.model_dump(exclude_unset=True)
        return await prisma.customerpreferences.upsert(
            where={"customer_id": customer_id},
            data={
                "create": {
                    "customer_id": customer_id,
                    **update_data
                },
                "update": update_data
            }
        )
