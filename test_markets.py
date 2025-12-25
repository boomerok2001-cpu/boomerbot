import asyncio
import aiohttp
import time

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

async def test_markets():
    async with aiohttp.ClientSession() as session:
        print(f"--- Testing {GAMMA_API}/markets ---")
        try:
            async with session.get(f"{GAMMA_API}/markets", params={"limit": 1, "active": "true"}) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Got {len(data)} items")
                    if data: print(f"Sample: {data[0].get('question')}")
                else:
                    print(await resp.text())
        except Exception as e:
            print(f"Error: {e}")

        print(f"\n--- Testing {DATA_API}/markets ---")
        try:
            async with session.get(f"{DATA_API}/markets", params={"limit": 1, "active": "true"}) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Got {len(data)} items")
                    if data: print(f"Sample: {data[0]}") # Data API structure might be different
                else:
                    print(await resp.text())
        except Exception as e:
             print(f"Error: {e}")

        
        # Test /events too as data-api uses events mostly
        print(f"\n--- Testing {DATA_API}/events ---")
        try:
            async with session.get(f"{DATA_API}/events", params={"limit": 1, "active": "true"}) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Got {len(data)} items")
                    if data: print(f"Sample: {data[0].get('title')}")
                else:
                    print(await resp.text())
        except Exception as e:
             print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_markets())
