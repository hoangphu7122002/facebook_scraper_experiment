"""Human-like browser behavior helpers.

Knowledge.md Layer 5 says FB ML models flag uniform timing / instant clicks /
24-7 activity. We don't fully simulate a human, but we randomize delays and
do smooth scrolls so behavior stays in a reasonable band for low-volume use.

Public API:
    human_scroll(page, scrolls)    — scroll a feed with reading pauses
    sleep_random(low, high)        — unified random delay
"""
import asyncio
import random


async def sleep_random(low: float, high: float) -> None:
    await asyncio.sleep(random.uniform(low, high))


async def human_scroll(page, scrolls: int, delay_range=(1.8, 3.6)) -> None:
    """Scroll a feed in a human-ish way and stop early if height stops growing.

    Each iteration:
      1. Smooth scroll by a randomized distance.
      2. Sleep a randomized "reading" interval.
      3. Occasionally move the (virtual) mouse — simulates focus shifts.
      4. Detect stall: if scrollHeight didn't grow for 3 rounds, give up
         (FB has hit the end of the feed or paused infinite-load).
    """
    last_height = 0
    stalled = 0
    for i in range(scrolls):
        distance = random.randint(700, 1500)
        await page.evaluate(
            "(d) => window.scrollBy({ top: d, behavior: 'smooth' })", distance,
        )
        await sleep_random(*delay_range)

        # 30% chance to nudge the mouse — cheap behavioral entropy.
        if random.random() < 0.3:
            try:
                await page.mouse.move(
                    random.randint(40, VIEWPORT_W() - 40),
                    random.randint(120, VIEWPORT_H() - 120),
                    steps=random.randint(6, 18),
                )
            except Exception:
                pass

        height = await page.evaluate("() => document.body.scrollHeight")
        if height == last_height:
            stalled += 1
            if stalled >= 3:
                break
        else:
            stalled = 0
            last_height = height


def VIEWPORT_W() -> int:
    from config import VIEWPORT_MOBILE
    return VIEWPORT_MOBILE["width"]


def VIEWPORT_H() -> int:
    from config import VIEWPORT_MOBILE
    return VIEWPORT_MOBILE["height"]
