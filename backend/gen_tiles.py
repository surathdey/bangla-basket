"""One-off: generate two tile images with Gemini Nano Banana."""
import asyncio, os, base64
from pathlib import Path
from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage

load_dotenv(Path(__file__).parent / ".env")
API = os.getenv("EMERGENT_LLM_KEY")

JOBS = [
    ("tile-grocery.jpg", "hero-tile-grocery",
     "Vibrant market display of fresh halal groceries: raw halal meat cuts on a wooden board, "
     "whole fresh fish on crushed ice, and colorful vegetables and fruits in baskets. Bright "
     "natural daylight, appetizing supermarket marketing photography, rich colors, no text, no watermark."),
    ("tile-meal.jpg", "hero-tile-meal",
     "An inviting spread of freshly cooked South Asian and Bengali meals: fragrant biryani with "
     "rice, kebabs, chicken and mutton curry, and side dishes served in bowls on a warm-lit table, "
     "top-down home-style food photography, appetizing, rich colors, no text, no watermark."),
]


async def one(fname, sid, prompt):
    chat = LlmChat(api_key=API, session_id=sid, system_message="You are an image generation assistant.")
    chat.with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"])
    _, images = await chat.send_message_multimodal_response(UserMessage(text=prompt))
    if images:
        out = Path("/app/frontend/assets/brand") / fname
        out.write_bytes(base64.b64decode(images[0]["data"]))
        print("saved", out, out.stat().st_size)
    else:
        print("NO IMAGE for", fname)


async def main():
    for fname, sid, prompt in JOBS:
        await one(fname, sid, prompt)


if __name__ == "__main__":
    asyncio.run(main())
