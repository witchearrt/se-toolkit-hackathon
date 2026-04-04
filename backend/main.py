from fastapi import FastAPI

app = FastAPI(title="Recipe Bot API")

@app.get("/health")
async def health_check():
    return {"status": "ok"}
