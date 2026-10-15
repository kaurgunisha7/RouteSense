from fastapi import FastAPI
from app.routes.trip import router as trip_router

app = FastAPI(title="RouteSense API")

app.include_router(
    trip_router,
    prefix="/api/trips",
    tags=["Trips"]
)


@app.get("/")
def root():
    return {"message": "RouteSense API is running"}