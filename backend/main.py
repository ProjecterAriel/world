import os, base64, io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from jose import jwt, JWTError
from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, EmailStr, Field

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
SECRET = os.getenv("JWT_SECRET", "development-only-change-me")
ALGORITHM = "HS256"
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
mongo = None
db = None
try:
    uri = os.getenv("MONGODB_URI")
    if uri:
        mongo = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
        db = mongo[os.getenv("MONGODB_DB", "terra_ai")]
except Exception:
    db = None

app = FastAPI(title="Terra AI API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class RegisterIn(BaseModel):
    nickname: str = Field(min_length=2, max_length=32)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class PreferencesIn(BaseModel):
    preferences: dict

class EarthObjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "marker"
    geometry: dict
    properties: dict = {}

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=12000)

class WeatherIn(BaseModel):
    place: str = Field(min_length=1, max_length=160)

def token_for(user_id: str):
    return jwt.encode({"sub": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=30)}, SECRET, algorithm=ALGORITHM)

async def current_user(authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in")
    try:
        payload = jwt.decode(authorization[7:], SECRET, algorithms=[ALGORITHM])
        uid = payload.get("sub")
    except JWTError:
        raise HTTPException(401, "Session expired")
    if not uid or db is None:
        raise HTTPException(503, "Database is not configured")
    user = await db.users.find_one({"_id": uid}, {"password": 0})
    if not user:
        raise HTTPException(401, "Account not found")
    return user

def public_user(user):
    return {"id": str(user["_id"]), "nickname": user["nickname"], "email": user["email"]}

@app.get("/api/health")
async def health():
    state = "not_configured"
    if db is not None:
        try:
            await mongo.admin.command("ping")
            state = "connected"
        except Exception:
            state = "disconnected"
    return {"ok": True, "service": "terra-ai", "database": state}

@app.post("/api/auth/register")
async def register(data: RegisterIn):
    if db is None: raise HTTPException(503, "Set MONGODB_URI in Render environment")
    email = data.email.lower()
    if await db.users.find_one({"email": email}): raise HTTPException(409, "Email already registered")
    uid = __import__("uuid").uuid4().hex
    user = {"_id": uid, "nickname": data.nickname.strip(), "email": email, "password": pwd.hash(data.password), "created_at": datetime.now(timezone.utc)}
    await db.users.insert_one(user)
    return {"token": token_for(uid), "user": public_user(user)}

@app.post("/api/auth/login")
async def login(data: LoginIn):
    if db is None: raise HTTPException(503, "Set MONGODB_URI in Render environment")
    user = await db.users.find_one({"email": data.email.lower()})
    if not user or not pwd.verify(data.password, user["password"]): raise HTTPException(401, "Incorrect email or password")
    return {"token": token_for(user["_id"]), "user": public_user(user)}

@app.get("/api/auth/me")
async def me(user=Depends(current_user)):
    return {"user": public_user(user)}

@app.get("/api/config")
async def config():
    return {"cesiumIonToken": os.getenv("CESIUM_ION_TOKEN", ""), "weatherConfigured": bool(os.getenv("OPENWEATHER_API_KEY"))}

@app.get("/api/preferences")
async def get_preferences(user=Depends(current_user)):
    doc = await db.preferences.find_one({"user_id": user["_id"]})
    return {"preferences": doc.get("preferences", {}) if doc else {}}

@app.put("/api/preferences")
async def save_preferences(data: PreferencesIn, user=Depends(current_user)):
    await db.preferences.update_one({"user_id": user["_id"]}, {"$set": {"preferences": data.preferences, "updated_at": datetime.now(timezone.utc)}}, upsert=True)
    return {"ok": True}

@app.get("/api/earth/objects")
async def list_objects(user=Depends(current_user)):
    docs = await db.earth_objects.find({"user_id": user["_id"]}).to_list(500)
    for d in docs: d["id"] = str(d.pop("_id"))
    return {"objects": docs}

@app.post("/api/earth/objects")
async def create_object(data: EarthObjectIn, user=Depends(current_user)):
    doc = data.model_dump()
    doc.update({"user_id": user["_id"], "created_at": datetime.now(timezone.utc)})
    result = await db.earth_objects.insert_one(doc)
    return {"id": str(result.inserted_id), "ok": True}

@app.put("/api/earth/objects/{object_id}")
async def update_object(object_id: str, data: EarthObjectIn, user=Depends(current_user)):
    try:
        oid = ObjectId(object_id)
    except InvalidId:
        raise HTTPException(400, "Invalid object id")
    doc = data.model_dump()
    doc["updated_at"] = datetime.now(timezone.utc)
    # Older records may have been stored with a string id; support both
    # representations while always enforcing per-user ownership.
    result = await db.earth_objects.update_one(
        {"user_id": user["_id"], "$or": [{"_id": oid}, {"_id": object_id}]},
        {"$set": doc}
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Object not found for this account")
    return {"ok": True}

@app.delete("/api/earth/objects")
async def clear_objects(user=Depends(current_user)):
    result = await db.earth_objects.delete_many({"user_id": user["_id"]})
    return {"ok": True, "deleted": result.deleted_count}

@app.post("/api/ai/chat")
async def ai_chat(data: ChatIn, user=Depends(current_user)):
    key = os.getenv("GROQ_API_KEY")
    if not key: raise HTTPException(503, "GROQ_API_KEY is not configured")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"), "messages": [{"role":"system","content":"You are Terra AI, a helpful assistant for Earth science, geography and weather. Be accurate and state uncertainty."},{"role":"user","content":data.message}]})
    if r.status_code >= 400: raise HTTPException(r.status_code, "AI provider error: " + r.text[:400])
    return {"reply": r.json()["choices"][0]["message"]["content"]}

@app.get("/api/geocode")
async def geocode(query: str, user=Depends(current_user)):
    query = query.strip()
    if not query or len(query) > 160:
        raise HTTPException(400, "Enter a place or country name")
    headers = {"User-Agent": "TerraAI/1.0 (geographic search)"}
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "polygon_geojson": 1,
        "extratags": 1,
        "namedetails": 1,
        "limit": 6,
        "accept-language": "ru,en"
    }
    async with httpx.AsyncClient(timeout=25, headers=headers) as client:
        response = await client.get("https://nominatim.openstreetmap.org/search", params=params)
    if response.status_code >= 400:
        raise HTTPException(502, "Geographic search provider is unavailable")
    results = response.json()
    # Prefer a country/admin boundary when the query names a country, while
    # retaining city and settlement results for ordinary place searches.
    results.sort(key=lambda item: (
        0 if item.get("addresstype") == "country" or
             (item.get("class") == "boundary" and item.get("type") == "administrative") else 1,
        -float(item.get("importance", 0))
    ))
    # Resolve the flag of the exact searched administrative entity (country,
    # region, island, etc.) through its own Wikidata item. Never substitute
    # the sovereign country's flag for a region that has no regional flag.
    async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "TerraAI/1.0 (geographic flag lookup)"}) as client:
        for item in results:
            tags = item.get("extratags") or {}
            flag = tags.get("flag") or tags.get("flag_image")
            qid = tags.get("wikidata")
            if qid and qid.startswith("Q"):
                try:
                    entity_response = await client.get(
                        "https://www.wikidata.org/w/api.php",
                        params={"action": "wbgetentities", "ids": qid, "props": "claims", "format": "json"}
                    )
                    entity_response.raise_for_status()
                    entity = entity_response.json().get("entities", {}).get(qid, {})
                    claims = entity.get("claims", {})
                    statements = claims.get("P41", [])
                    if statements:
                        filename = statements[0]["mainsnak"]["datavalue"]["value"]
                        from urllib.parse import quote
                        flag = "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(filename.replace(" ", "_")) + "?width=1200"
                except Exception:
                    pass
            if flag and not str(flag).startswith(("https://", "http://")):
                from urllib.parse import quote
                flag = "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(str(flag).replace(" ", "_")) + "?width=1200"
            item["flag_url"] = flag if flag and str(flag).startswith("https://") else None
            item["wikidata"] = qid
    return {"results": results}

@app.get("/api/flag-image")
async def flag_image(url: str, token: str):
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        uid = payload.get("sub")
    except JWTError:
        raise HTTPException(401, "Session expired")
    if not uid or db is None or not await db.users.find_one({"_id": uid}, {"_id": 1}):
        raise HTTPException(401, "Please sign in")
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"commons.wikimedia.org", "upload.wikimedia.org", "flagcdn.com"}:
        raise HTTPException(400, "Unsupported flag image source")
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers={"User-Agent": "TerraAI/1.0"}) as client:
        upstream = await client.get(url)
    if upstream.status_code >= 400 or not upstream.headers.get("content-type", "").startswith("image/"):
        raise HTTPException(502, "Flag image could not be loaded")
    return Response(content=upstream.content, media_type=upstream.headers.get("content-type", "image/png"), headers={"Cache-Control": "public, max-age=86400"})

@app.get("/api/weather/tiles/{layer}/{z}/{x}/{y}.png")
async def weather_tile(layer: str, z: int, x: int, y: int, token: str):
    # Cesium image requests cannot conveniently attach the app's Authorization header,
    # so validate the existing short-lived app JWT passed as a query parameter.
    allowed_layers = {"temp_new", "clouds_new", "precipitation_new", "wind_new", "pressure_new"}
    if layer not in allowed_layers or not (0 <= z <= 18) or x < 0 or y < 0 or x >= 2 ** z or y >= 2 ** z:
        raise HTTPException(400, "Invalid weather tile")
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        uid = payload.get("sub")
    except JWTError:
        raise HTTPException(401, "Session expired")
    if not uid or db is None or not await db.users.find_one({"_id": uid}, {"_id": 1}):
        raise HTTPException(401, "Please sign in")
    key = os.getenv("OPENWEATHER_API_KEY")
    if not key:
        raise HTTPException(503, "OPENWEATHER_API_KEY is not configured")
    url = f"https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png"
    async with httpx.AsyncClient(timeout=20) as client:
        upstream = await client.get(url, params={"appid": key})
    if upstream.status_code >= 400:
        raise HTTPException(502, "OpenWeather tile service error")
    return Response(content=upstream.content, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})

@app.get("/api/weather")
async def weather(place: str, user=Depends(current_user)):
    key = os.getenv("OPENWEATHER_API_KEY")
    if not key: raise HTTPException(503, "OPENWEATHER_API_KEY is not configured")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get("https://api.openweathermap.org/data/2.5/forecast", params={"q": place, "appid": key, "units":"metric"})
    if r.status_code >= 400: raise HTTPException(404, "Weather location not found")
    return r.json()

@app.post("/api/ai/image")
async def generate_image(data: ChatIn, user=Depends(current_user)):
    account, key = os.getenv("CLOUDFLARE_ACCOUNT_ID"), os.getenv("CLOUDFLARE_API_TOKEN")
    if not account or not key: raise HTTPException(503, "Cloudflare AI credentials are not configured")
    model = os.getenv("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json={"prompt": data.message})
    if r.status_code >= 400: raise HTTPException(r.status_code, "Image provider error: " + r.text[:400])
    payload = r.json().get("result", {})
    if payload.get("image"): return {"image": "data:image/png;base64," + payload["image"]}
    raise HTTPException(502, "Image provider returned no image")

@app.get("/", response_class=HTMLResponse)
async def home():
    return (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

app.mount("/", StaticFiles(directory=ROOT / "frontend"), name="frontend")
