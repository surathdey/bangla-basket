"""One-off: generate the Thali Party Order tile image with Gemini Nano Banana."""
import asyncio, os, base64
from pathlib import Path
from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage

load_dotenv(Path(__file__).parent / ".env")
API = os.getenv("EMERGENT_LLM_KEY")

PROMPT = (
    "A generous takeout-style party thali platter: a disposable compartment tray filled with "
    "fragrant white rice, rich mutton and chicken curry, yellow dal, a vegetable curry, luchi/poori bread, "
    "and a sweet dessert, arranged neatly. Several trays stacked for a party order in the background. "
    "Warm appetizing South Asian / Bengali catering food photography, top-down, bright natural light, "
    "rich colors, no text, no watermark."
)


async def main():
    chat = LlmChat(api_key=API, session_id="hero-tile-thali", system_message="You are an image generation assistant.")
    chat.with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"])
    _, images = await chat.send_message_multimodal_response(UserMessage(text=PROMPT))
    if images:
        out = Path("/app/frontend/assets/brand/tile-thali.jpg")
        out.write_bytes(base64.b64decode(images[0]["data"]))
        print("saved", out, out.stat().st_size)
    else:
        print("NO IMAGE")


if __name__ == "__main__":
    asyncio.run(main())
