from app.prisma_client import Prisma

prisma = Prisma()


async def get_prisma() -> Prisma:
    """Dependency provider or helper to get the Prisma client."""
    return prisma
