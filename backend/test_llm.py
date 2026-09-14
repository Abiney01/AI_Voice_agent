import asyncio
import logging
import sys
from dotenv import load_dotenv

# Configure basic logging to see library outputs
logging.basicConfig(level=logging.INFO)

# Load environment variables from .env
load_dotenv()

from app.services.openai.conversation_service import ConversationService

async def main():
    print("Initializing ConversationService...")
    svc = ConversationService()
    
    # Simple message test
    user_msg = "Hello! What is your name and what can you do?"
    print(f"\nSending direct chat request with message: '{user_msg}'")
    
    try:
        response = await svc.chat(
            customer_name="Test User",
            preferences={},
            menu_summary="Sample Menu: Butter Chicken (260 INR), Garlic Naan (50 INR)",
            current_order={"items": []},
            recent_memories=[],
            conversation_history=[],
            user_message=user_msg
        )
        print("\n--- LLM Response ---")
        print(response)
        print("--------------------")
        
        # Check if the fallback error message was returned
        if "trouble processing your request" in response:
            print("\n❌ ERROR: Received the fallback error message. The actual API call failed.")
            print("Please check the terminal logs above or run with DEBUG logging to see the exception details.")
        else:
            print("\n✅ SUCCESS: LLM responded correctly!")
            
    except Exception as e:
        print("\n❌ EXCEPTION OCCURRED:", file=sys.stderr)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
