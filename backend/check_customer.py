import asyncio
from app.core.prisma import prisma

async def main():
    await prisma.connect()
    try:
        # Check customer 3
        cust = await prisma.customer.find_unique(
            where={"id": 3},
            include={"preferences": True}
        )
        print("--- Customer 3 Details ---")
        print("Found:", cust is not None)
        if cust:
            print("Name:", cust.name)
            print("Phone number:", cust.phone_number)
            print("Preferences:", cust.preferences)
            
            # Check orders for customer 3
            orders = await prisma.order.find_many(
                where={"customer_id": 3},
                include={"items": True}
            )
            print(f"Orders count: {len(orders)}")
            for o in orders:
                print(f"Order ID: {o.id}, Status: {o.status}, Items: {len(o.items)}")

            # Check memories for customer 3
            mems = await prisma.conversationsummary.find_many(
                where={"customer_id": 3}
            )
            print(f"Memories count: {len(mems)}")
    except Exception as e:
        print("Error checking Customer 3:", e)
    finally:
        await prisma.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
