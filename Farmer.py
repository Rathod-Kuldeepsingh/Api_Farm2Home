import json
import os
import base64
from fastapi import FastAPI, Form, HTTPException, Header
from fastapi.responses import StreamingResponse
from pymongo import MongoClient
import gridfs
from bson import ObjectId
from pydantic import BaseModel
import firebase_admin
from firebase_admin import auth, credentials
# changes

port = int(os.environ.get("PORT", 8000))  # 8000 for local, $PORT on Render
service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT")
if not service_account_path:
    raise ValueError("FIREBASE_SERVICE_ACCOUNT environment variable is not set!")

# Read and parse the JSON file
with open(service_account_path, 'r') as f:
    service_account_info = json.load(f)

# Create credentials
cred = credentials.Certificate(service_account_info)

# ----------------- Initialize FastAPI & MongoDB -----------------
app = FastAPI()
client = MongoClient(
    "mongodb+srv://Kuldeep:kuldeep123@rathods.tsq8f77.mongodb.net/profile_db?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"
)
db = client["Farmer_market"]
Product_collection = db["Product_list"]
fs = gridfs.GridFS(db)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ----------------- Models & Serializer -----------------
class Product(BaseModel):
    farmer_id: str
    name: str
    price: float
    quantity: int
    description: str = None
    image_url: str = None
    farmer_name: str = None

def serialize_product(product) -> dict:
    return {
        "id": str(product["_id"]),
        "farmer_id": product["farmer_id"],
        "farmer_name": product.get("farmer_name"),
        "name": product["name"],
        "price": product["price"],
        "quantity": product["quantity"],
        "description": product.get("description"),
        "image_url": product.get("image_url"),
    }

# ----------------- Helper Functions -----------------
def get_firebase_uid(id_token: str) -> str:
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token["uid"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Firebase token")

def save_base64_image(image_base64: str, name: str) -> str:
    try:
        if "," in image_base64:
            _, image_base64 = image_base64.split(",", 1)
        image_data = base64.b64decode(image_base64)

        if len(image_data) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image size must be < 5MB")

        file_id = fs.put(image_data, filename=f"{name}.png", content_type="image/png")
        return f"http://127.0.0.1:8000/images/{file_id}"
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Base64 image")

# ----------------- API Endpoints -----------------
@app.post("/products")
async def add_product(
    id_token: str = Form(...),
    name: str = Form(...),
    price: float = Form(...),
    quantity: int = Form(...),
    description: str = Form(None),
    image_base64: str = Form(None),
    farmer_name: str = Form(None),  # optional
):
    farmer_id = get_firebase_uid(id_token)

    image_url = save_base64_image(image_base64, name) if image_base64 else None

    product_dict = {
        "farmer_id": farmer_id,
        "farmer_name": farmer_name,
        "name": name,
        "price": price,
        "quantity": quantity,
        "description": description,
        "image_url": image_url,
    }

    try:
        result = Product_collection.insert_one(product_dict)
        created = Product_collection.find_one({"_id": result.inserted_id})
        return {"message": "✅ Product added successfully", "product": serialize_product(created)}
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save product")

@app.put("/products/{product_id}")
async def update_product(
    product_id: str,
    id_token: str = Form(...),
    name: str = Form(...),
    price: float = Form(...),
    quantity: int = Form(...),
    description: str = Form(None),
    image_base64: str = Form(None),
    farmer_name: str = Form(None),
):
    farmer_id = get_firebase_uid(id_token)

    product = Product_collection.find_one({"_id": ObjectId(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    image_url = product.get("image_url")
    if image_base64:
        image_url = save_base64_image(image_base64, name)

    update_data = {
        "farmer_id": farmer_id,
        "farmer_name": farmer_name,
        "name": name,
        "price": price,
        "quantity": quantity,
        "description": description,
        "image_url": image_url,
    }

    Product_collection.update_one({"_id": ObjectId(product_id)}, {"$set": update_data})
    updated = Product_collection.find_one({"_id": ObjectId(product_id)})
    return {"message": "✅ Product updated successfully", "product": serialize_product(updated)}

@app.delete("/products/{product_id}")
async def delete_product(product_id: str, id_token: str = Form(...)):
    farmer_id = get_firebase_uid(id_token)

    product = Product_collection.find_one({"_id": ObjectId(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product["farmer_id"] != farmer_id:
        raise HTTPException(status_code=403, detail="You cannot delete this product")

    Product_collection.delete_one({"_id": ObjectId(product_id)})
    return {"message": "✅ Product deleted successfully"}

@app.get("/products")
def get_products():
    products = list(Product_collection.find())
    return [serialize_product(p) for p in products]

@app.get("/products/{product_id}")
def get_product(product_id: str):
    product = Product_collection.find_one({"_id": ObjectId(product_id)})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return serialize_product(product)

@app.get("/images/{file_id}")
async def get_image(file_id: str):
    try:
        grid_file = fs.get(ObjectId(file_id))
        return StreamingResponse(grid_file, media_type=grid_file.content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
