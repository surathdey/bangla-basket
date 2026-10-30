"""One-off: generate a fresh-groceries hero image with Gemini Nano Banana."""
import asyncio
import os
import base64
from pathlib import Path
from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage

load_dotenv(Path(__file__).parent / ".env")

OUT = Path("/app/frontend/assets/brand/hero-fresh.jpg")
PROMPT = (
    "Wide, bright food photograph of an abundant fresh grocery spread on a clean light "
    "wooden market table: colorful fresh vegetables and leafy greens, ripe fruits, fresh "
    "fish on ice, cuts of raw halal meat, bowls of rice and lentils, and vibrant spices. "
    "Overhead-to-45-degree angle, natural daylight, crisp and appetizing, professional "
    "supermarket marketing photography, rich saturated colors, no text, no watermark."
)


async def main():
    api_key = os.getenv("EMERGENT_LLM_KEY")
    chat = LlmChat(api_key=api_key, session_id="hero-gen-1", system_message="You are an image generation assistant.")
    chat.with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"])
    text, images = await chat.send_message_multimodal_response(UserMessage(text=PROMPT))
    print("text:", (text or "")[:60])
    if not images:
        print("NO IMAGE RETURNED")
        return
    img = images[0]
    print("mime:", img["mime_type"], "data head:", img["data"][:10])
    OUT.write_bytes(base64.b64decode(img["data"]))
    print("saved:", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    asyncio.run(main())
