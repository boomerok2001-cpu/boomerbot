import asyncio
import aiohttp

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

async def test_find_trades_endpoint():
    async with aiohttp.ClientSession() as session:
        # 1. Get a valid market/asset info
        print("Fetching a market...")
        market_id = None
        asset_id = None
        slug = None
        
        try:
            async with session.get(f"{GAMMA_API}/markets", params={"limit": 1, "active": "true"}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        m = data[0]
                        market_id = m.get('id')
                        # Looking for asset_id, usually in token_id or similar
                        # Polymarket structure is complex, often clobTokenIds or outcome token ids.
                        # For simple markets (Yes/No), maybe 'questionID' or 'conditionId'?
                        # Let's just print keys to be sure what to use.
                        print(f"Market Keys: {m.keys()}")
                        slug = m.get('slug')
                        print(f"Market ID: {market_id}, Slug: {slug}")
                else:
                    print(f"Gamma Markets failed: {resp.status}")
        except Exception as e:
            print(f"Gamma fail: {e}")

        if not slug:
            print("No market found to test.")
            return

        # 2. Test Data API with different params
        # We know /trades works.
        params_to_test = [
            {"slug": slug},
            {"market": slug},
            {"market_slug": slug},
            {"market": market_id},
            {"id": market_id}
        ]
        
        for params in params_to_test:
            print(f"\nTesting {DATA_API}/trades with {params}...")
            try:
                async with session.get(f"{DATA_API}/trades", params=params) as resp:
                    print(f"Status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"Result count: {len(data)}")
                        if len(data) > 0:
                            print("SUCCESS! Found trades.")
                            break
                    else:
                        print(await resp.text())
            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_find_trades_endpoint())
