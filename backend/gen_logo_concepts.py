"""Generate Stock & Supper logo concepts (Nano Banana). Saves to uploads/logos/."""
import asyncio, base64, logging, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from emergentintegrations.llm.chat import LlmChat, UserMessage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("logos")
KEY = os.getenv("EMERGENT_LLM_KEY")
OUT = Path("/app/backend/uploads/logos"); OUT.mkdir(parents=True, exist_ok=True)

PALETTE = ("Palette: deep pine green (#14532D), warm maple amber (#E0A83B), soft terracotta accent "
           "(#C1553B), charcoal text (#232A2E), on a soft cream background (#FAF6EF). Modern, premium, "
           "friendly, inclusive, broadly Canadian (not tied to any one region or country).")
BASE = ("Clean flat minimalist VECTOR logo for a Canadian grocery + weekly meal delivery brand. "
        "Horizontal lockup. Bold modern geometric sans-serif wordmark reading EXACTLY 'STOCK & SUPPER' "
        "(ampersand in amber), with a small light tagline underneath reading EXACTLY "
        "'Groceries & weekly meals, delivered'. Correct spelling, crisp kerning, high resolution, "
        "professional, lots of clean whitespace. " + PALETTE)

CONCEPTS = {
    "concept1_basket_maple.png": BASE + " ICON above the wordmark: a simple line-art grocery basket "
        "holding fresh produce with ONE small maple leaf subtly integrated into the handle.",
    "concept2_basket_door.png": BASE + " ICON: a grocery basket cleverly merged with a house/door outline, "
        "symbolising fresh groceries delivered to your doorstep.",
    "concept3_basket_bowl.png": BASE + " ICON: a grocery basket beside a steaming lidded meal bowl, "
        "representing both groceries AND ready weekly meals in one mark.",
    "concept4_monogram.png": BASE + " ICON: a clean rounded badge monogram of the letters 'S&S' with a "
        "single leaf sprout, simple and iconic.",
}

async def gen(fname, prompt):
    chat = (LlmChat(api_key=KEY, session_id=f"logo-{fname}", system_message="You are a world-class brand logo designer.")
            .with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"]))
    _t, images = await chat.send_message_multimodal_response(UserMessage(text=prompt))
    if images:
        (OUT / fname).write_bytes(base64.b64decode(images[0]["data"]))
        log.info(f"saved {fname}")
    else:
        log.warning(f"no image for {fname}")

async def main():
    for f, p in CONCEPTS.items():
        try: await gen(f, p)
        except Exception as e: log.warning(f"failed {f}: {e}")
    log.info("DONE")

if __name__ == "__main__":
    asyncio.run(main())
