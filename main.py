import os
import random
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import db, create_document
from bson import ObjectId

app = FastAPI(title="Price Compare API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Models
# -----------------------------
class PricePoint(BaseModel):
    date: datetime
    price: float

class PlatformPrice(BaseModel):
    platform: str
    price: float
    currency: str = "INR"
    url: Optional[str] = None
    rating: Optional[float] = Field(default=None, ge=0, le=5)
    delivery: Optional[str] = None
    last_updated: datetime
    history: List[PricePoint] = Field(default_factory=list)

class ProductResult(BaseModel):
    id: str
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None
    image: Optional[str] = None
    platforms: List[PlatformPrice]

class SearchResponse(BaseModel):
    query: str
    results: List[ProductResult]
    filters: Dict[str, Any]
    generated_at: datetime


# -----------------------------
# Catalogs & Utilities
# -----------------------------
PLATFORMS = [
    "Amazon",
    "Flipkart",
    "Myntra",
    "AJIO",
    "Meesho",
    "Tata Cliq",
    "Croma",
]

CATEGORIES = [
    "Mobiles",
    "Headphones",
    "Laptops",
    "Shoes",
    "Fashion",
    "Appliances",
    "TVs",
    "Wearables",
]

BRANDS = [
    "Apple", "Samsung", "Sony", "Dell", "HP", "Lenovo", "Asus",
    "Nike", "Adidas", "Puma", "Boat", "OnePlus", "Xiaomi"
]

SAMPLE_IMAGES = [
    "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=800",
    "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=800",
    "https://images.unsplash.com/photo-1512496015851-a90fb38ba796?w=800",
]


def normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())


def rand_price(base: float) -> float:
    variance = base * 0.15
    return round(random.uniform(base - variance, base + variance), 2)


def make_history(base: float, days: int = 14) -> List[PricePoint]:
    pts = []
    cur = base
    for i in range(days, -1, -1):
        cur = max(100.0, rand_price(cur))
        pts.append(PricePoint(date=datetime.now(timezone.utc) - timedelta(days=i), price=cur))
    return pts


def ensure_product_in_db(name: str, brand: Optional[str], category: Optional[str]) -> Dict[str, Any]:
    norm = normalize(name)
    existing = db["product"].find_one({"normalized_name": norm}) if db else None
    if existing:
        return existing
    # Create new sample product
    doc = {
        "name": name,
        "normalized_name": norm,
        "brand": brand,
        "category": category or "General",
        "image": random.choice(SAMPLE_IMAGES),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    if db is None:
        # fallback without DB
        return doc
    inserted_id = db["product"].insert_one(doc).inserted_id
    doc["_id"] = inserted_id
    # Seed platform prices
    base = random.uniform(499, 49999)
    seeded = []
    for p in PLATFORMS:
        price = rand_price(base)
        pp = {
            "product_id": str(inserted_id),
            "platform": p,
            "price": price,
            "currency": "INR",
            "url": f"https://{p.replace(' ', '').lower()}.com/search?q={norm}",
            "rating": round(random.uniform(3.5, 5.0), 1),
            "delivery": random.choice(["2-3 days", "Next day", "Standard (3-5 days)"]),
            "last_updated": datetime.now(timezone.utc),
            "history": [h.model_dump() for h in make_history(price)],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        seeded.append(pp)
    if seeded:
        db["priceentry"].insert_many(seeded)
    return doc


def find_or_generate_prices(product_doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    if db is None or ("_id" not in product_doc):
        # Generate ephemeral data
        base = random.uniform(499, 49999)
        out = []
        for p in PLATFORMS:
            price = rand_price(base)
            out.append({
                "platform": p,
                "price": price,
                "currency": "INR",
                "url": f"https://{p.replace(' ', '').lower()}.com",
                "rating": round(random.uniform(3.5, 5.0), 1),
                "delivery": random.choice(["2-3 days", "Next day", "Standard (3-5 days)"]),
                "last_updated": datetime.now(timezone.utc),
                "history": [h.model_dump() for h in make_history(price)],
            })
        return out
    # Pull from DB
    items = list(db["priceentry"].find({"product_id": str(product_doc["_id"]) }))
    # if empty, seed now
    if not items:
        base = random.uniform(499, 49999)
        seeded = []
        for p in PLATFORMS:
            price = rand_price(base)
            pp = {
                "product_id": str(product_doc["_id"]),
                "platform": p,
                "price": price,
                "currency": "INR",
                "url": f"https://{p.replace(' ', '').lower()}.com/search?q={product_doc.get('normalized_name','')}",
                "rating": round(random.uniform(3.5, 5.0), 1),
                "delivery": random.choice(["2-3 days", "Next day", "Standard (3-5 days)"]),
                "last_updated": datetime.now(timezone.utc),
                "history": [h.model_dump() for h in make_history(price)],
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            seeded.append(pp)
        if seeded:
            db["priceentry"].insert_many(seeded)
            items = seeded
    return items


# -----------------------------
# Routes
# -----------------------------
@app.get("/")
def read_root():
    return {"message": "Price Compare Backend running"}


@app.get("/api/catalogs")
def get_catalogs():
    return {
        "categories": CATEGORIES,
        "brands": BRANDS,
        "platforms": PLATFORMS,
        "generated_at": datetime.now(timezone.utc)
    }


@app.get("/api/search", response_model=SearchResponse)
def search_products(
    q: str = Query(..., description="Product name to search"),
    category: Optional[str] = None,
    brand: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
):
    # Ensure product exists (seed DB if empty)
    product_doc = ensure_product_in_db(q, brand, category)

    # Gather prices
    prices = find_or_generate_prices(product_doc)

    # Apply price range filters
    if price_min is not None or price_max is not None:
        def in_range(v: float) -> bool:
            if price_min is not None and v < price_min:
                return False
            if price_max is not None and v > price_max:
                return False
            return True
        prices = [p for p in prices if in_range(p["price"])]

    # Build response result
    result = ProductResult(
        id=str(product_doc.get("_id", ObjectId())),
        name=product_doc.get("name", q),
        brand=product_doc.get("brand"),
        category=product_doc.get("category"),
        image=product_doc.get("image"),
        platforms=[PlatformPrice(**{
            **p,
            "last_updated": p["last_updated"] if isinstance(p["last_updated"], datetime) else datetime.fromisoformat(str(p["last_updated"]))
        }) for p in prices]
    )

    response = SearchResponse(
        query=q,
        results=[result],
        filters={
            "category": category,
            "brand": brand,
            "price_min": price_min,
            "price_max": price_max,
        },
        generated_at=datetime.now(timezone.utc)
    )

    # Persist search record (if DB available)
    try:
        if db is not None:
            create_document("searchrecord", {
                "query": q,
                "brand": brand,
                "category": category,
                "price_min": price_min,
                "price_max": price_max,
                "results_count": len(result.platforms),
            })
    except Exception:
        pass

    return response


@app.get("/api/search/recent")
def recent_searches(limit: int = 8):
    items: List[Dict[str, Any]] = []
    if db is not None:
        try:
            cursor = db["searchrecord"].find({}).sort("created_at", -1).limit(limit)
            for doc in cursor:
                items.append({
                    "query": doc.get("query"),
                    "brand": doc.get("brand"),
                    "category": doc.get("category"),
                    "price_min": doc.get("price_min"),
                    "price_max": doc.get("price_max"),
                    "results_count": doc.get("results_count", 0),
                    "created_at": doc.get("created_at"),
                })
        except Exception:
            items = []
    # Fallback sample if no DB
    if not items:
        samples = [
            {"query": "iPhone 15", "brand": "Apple", "category": "Mobiles", "results_count": 6},
            {"query": "Sony WH-1000XM5", "brand": "Sony", "category": "Headphones", "results_count": 5},
            {"query": "MacBook Air", "brand": "Apple", "category": "Laptops", "results_count": 6},
        ]
        items = samples[:limit]
    return {"items": items, "generated_at": datetime.now(timezone.utc)}


@app.get("/api/trending")
def trending_deals(limit: int = 6):
    # Generate or pull deals
    items = []
    for _ in range(limit):
        name = random.choice([
            "iPhone 15", "Samsung Galaxy S23", "Sony WH-1000XM5",
            "Nike Air Max", "Dell XPS 13", "MacBook Air M2"
        ])
        brand = random.choice(["Apple", "Samsung", "Sony", "Nike", "Dell", "Apple"])  # duplicate to bias
        category = random.choice(["Mobiles", "Headphones", "Shoes", "Laptops"])
        base = random.uniform(999, 149999)
        platform_prices = []
        for p in random.sample(PLATFORMS, k=min(4, len(PLATFORMS))):
            pr = rand_price(base)
            platform_prices.append({
                "platform": p,
                "price": pr,
                "currency": "INR",
                "url": f"https://{p.replace(' ', '').lower()}.com/search?q={name}",
                "last_updated": datetime.now(timezone.utc),
            })
        lowest = min(platform_prices, key=lambda x: x["price"]) if platform_prices else None
        items.append({
            "name": name,
            "brand": brand,
            "category": category,
            "image": random.choice(SAMPLE_IMAGES),
            "platforms": platform_prices,
            "lowest": lowest,
        })
    return {"items": items, "generated_at": datetime.now(timezone.utc)}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
