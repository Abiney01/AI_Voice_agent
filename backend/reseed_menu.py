"""
Script to clear old menu items and reseed with new menu.
"""
import asyncio
from app.core.prisma import prisma
from seed_menu import MENU_DATA


async def main():
    await prisma.connect()
    try:
        count = await prisma.menuitem.count()
        print(f"Found {count} existing menu items — clearing...")
        # delete_many returns the count; foreign key constraint requires order_items gone first
        # Use raw SQL to truncate safely in the right order
        await prisma.execute_raw("DELETE FROM order_items WHERE menu_item_id IN (SELECT id FROM menu_items)")
        await prisma.execute_raw("DELETE FROM menu_items")
        print("Old menu cleared.")

        for item_data in MENU_DATA:
            await prisma.menuitem.create(data=item_data)
        print(f"Seeded {len(MENU_DATA)} menu items.")
    finally:
        await prisma.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
