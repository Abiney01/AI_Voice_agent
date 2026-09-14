from typing import Optional, Tuple
from app.prisma_client.models import Customer
from app.repositories.customer_repository import CustomerRepository
from app.schemas.customer import CustomerIdentify, CustomerPreferencesUpdate


class CustomerService:
    def __init__(self):
        self.repo = CustomerRepository()

    async def identify(self, data: CustomerIdentify) -> Tuple[Customer, bool]:
        """
        Register or look up a customer by phone number.
        Returns (customer, is_returning).
        """
        existing = await self.repo.get_by_phone(data.phone_number)
        if existing:
            # Update name if provided
            if data.name and not existing.name:
                existing = await self.repo.update_name(existing, data.name)
            return existing, True

        customer = await self.repo.create(data.phone_number, data.name)
        return customer, False

    async def get_profile(self, customer_id: int) -> Optional[Customer]:
        return await self.repo.get_by_id(customer_id)

    async def update_preferences(
        self, customer_id: int, data: CustomerPreferencesUpdate
    ):
        return await self.repo.update_preferences(customer_id, data)
