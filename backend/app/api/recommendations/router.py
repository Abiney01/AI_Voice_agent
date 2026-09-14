from fastapi import APIRouter
from app.services.recommendations.recommendation_service import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/{customer_id}", summary="Get personalized recommendations for a customer")
async def get_recommendations(customer_id: int):
    service = RecommendationService()
    recommendations = await service.get_recommendations(customer_id)
    return {"customer_id": customer_id, "recommendations": recommendations}
