"""Generate two wide hero banners for the customer website (Nano Banana).

Saves fixed filenames under /app/backend/uploads/menu/ so the frontend can
reference them directly:
  - hero-grocery.png
  - hero-meal.png
"""
import asyncio
import base64
import logging
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("banners")

KEY = os.getenv("EMERGENT_LLM_KEY")
OUT = Path("/app/backend/uploads/menu")
OUT.mkdir(parents=True, exist_ok=True)

BANNERS = {
    "hero-grocery.png": (
        "Ultra-wide cinematic hero banner, 16:9 letterbox composition, of a vibrant "
        "halal grocery spread on a clean market table: fresh green vegetables, whole "
        "fish on ice, cuts of red meat, colourful spices in bowls, Bengali sweets, "
        "and pantry staples. Bright natural daylight, rich saturated colours, shallow "
        "depth of field, professional food-market photography. Leave calm empty space "
        "on the left for text overlay. No text, no watermark, no people."
    ),
    "hero-meal.png": (
        "Ultra-wide cinematic hero banner, 16:9 letterbox composition, of an assortment "
        "of freshly cooked Bengali home-style meals arranged as a flat-lay: steaming rice, "
        "fish curry, mutton qorma, dal, mixed vegetable dishes and garnishes in rustic "
        "bowls on a warm wooden table. Appetizing, restaurant-quality plating, soft warm "
        "lighting, rich colours. Leave calm empty space on the left for text overlay. "
        "No text, no watermark, no people."
    ),
}


async def gen(fname: str, prompt: str):
    chat = LlmChat(
        api_key=KEY,
        session_id=f"banner-{uuid.uuid4().hex[:8]}",
        system_message="You generate high-quality wide marketing banner photography.",
    ).with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"])
    _t, images = await chat.send_message_multimodal_response(UserMessage(text=prompt))
    if not images:
        log.warning(f"no image for {fname}")
        return
    raw = base64.b64decode(images[0]["data"])
    (OUT / fname).write_bytes(raw)
    log.info(f"saved {fname} ({len(raw)} bytes)")


async def main():
    for fname, prompt in BANNERS.items():
        try:
            await gen(fname, prompt)
        except Exception as e:
            log.warning(f"failed {fname}: {e}")
    log.info("DONE")


if __name__ == "__main__":
    asyncio.run(main())
