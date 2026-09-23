from fastapi import FastAPI

from app.routes import router


app = FastAPI(
    title="Black Coordinates List - IP Resolution Service",
    description="Service A - resolves IP addresses into geographic data",
    version="1.0.0",
)

app.include_router(router)