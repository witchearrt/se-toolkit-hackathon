import httpx
import asyncio

async def test():
    async with httpx.AsyncClient(timeout=5) as c:
        try:
            r = await c.get("http://qwen-code-api:8080/health")
            print(f"Health: {r.status_code} {r.text[:100]}")
        except Exception as e:
            print(f"Health error: {e}")
        
        try:
            headers = {"Content-Type": "application/json", "X-API-Key": "xxjfnbdhb9mTIWlOL9EQVkBWEGRGOEIR7zTkRR8o8UzX7JV00FhUE3A0tYbmsT9IKleq5WCUAYOrAxKEa6RwDA"}
            payload = {"model": "coder-model", "messages": [{"role": "user", "content": "say ok"}]}
            r = await c.post("http://qwen-code-api:8080/v1/chat/completions", json=payload, headers=headers)
            print(f"Chat: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"Chat error: {e}")

asyncio.run(test())
