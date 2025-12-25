import asyncio
import aiohttp

GAMMA_API = "https://gamma-api.polymarket.com"

async def test_market_trades():
    market_id = "1" # Assuming 1 exists, or need a real one.
    # Let's get a real market ID first
    async with aiohttp.ClientSession() as session:
        market_id = None
        async with session.get(f"{GAMMA_API}/markets", params={"limit": 1, "active": "true"}) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data:
                    market_id = data[0].get('id')
                    print(f"Using Market ID: {market_id}")

        if market_id:
            print(f"--- Testing {GAMMA_API}/markets/{market_id}/trades ---")
            try:
                async with session.get(f"{GAMMA_API}/markets/{market_id}/trades", params={"limit": 1}) as resp:
                    print(f"Status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"Got {len(data)} trades")
                    else:
                        print(await resp.text())
            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_market_trades())
