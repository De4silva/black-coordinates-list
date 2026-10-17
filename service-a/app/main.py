from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.user_gateway import user_gateway

from app.routes import router


@asynccontextmanager
async def lifespan(app):
    try:
        yield
    finally:
        user_gateway.close()


app = FastAPI(
    lifespan=lifespan,
    title="Black Coordinates List - IP Resolution Service",
    description="Service A - resolves IP addresses into geographic data",
    version="1.0.0",
)

app.include_router(router)
