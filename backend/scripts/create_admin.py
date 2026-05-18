"""
Script to create an admin user in PhuongAnh-TTS.

Usage:
    python -m scripts.create_admin --email admin@example.com --password your_password
"""

import asyncio
import argparse
import secrets
import sys
import os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from bson import ObjectId

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def create_admin_user(
    mongodb_uri: str,
    db_name: str,
    email: str,
    password: str,
    username: str = None
) -> dict:
    """Create an admin user in the database."""
    
    client = AsyncIOMotorClient(mongodb_uri)
    db = client[db_name]
    users = db.users
    
    existing = await users.find_one({"email": email.lower().strip()})
    if existing:
        print(f"User with email {email} already exists!")
        return {"error": "Email already registered"}
    
    now = datetime.utcnow()
    verification_token = secrets.token_urlsafe(32)
    
    user_doc = {
        "email": email.lower().strip(),
        "password_hash": pwd_context.hash(password),
        "role": "admin",
        "username": username or email.split("@")[0],
        "phone": None,
        "subscription_plan": "pro",
        "subscription_status": "active",
        "subscription_expires_at": None,
        "is_verified": True,
        "verification_token": verification_token,
        "last_login": None,
        "created_at": now,
        "updated_at": now,
        "metadata": {
            "registration_source": "admin_script",
            "email_verified": True,
        }
    }
    
    result = await users.insert_one(user_doc)
    user_id = str(result.inserted_id)
    
    await db.subscriptions.insert_one({
        "user_id": ObjectId(user_id),
        "plan": "pro",
        "started_at": now,
        "expires_at": None,
        "auto_renew": False,
        "payment_history": [],
        "status": "active"
    })
    
    await db.usage_logs.insert_one({
        "user_id": ObjectId(user_id),
        "action": "admin_created",
        "timestamp": now,
        "metadata": {"source": "admin_script"}
    })
    
    client.close()
    
    return {
        "id": user_id,
        "email": email,
        "username": user_doc["username"],
        "role": "admin",
        "subscription_plan": "pro"
    }


def main():
    parser = argparse.ArgumentParser(description="Create an admin user")
    parser.add_argument("--email", "-e", required=True, help="Admin email")
    parser.add_argument("--password", "-p", required=True, help="Admin password")
    parser.add_argument("--username", "-u", help="Admin username (optional)")
    parser.add_argument(
        "--mongodb-uri", 
        default="mongodb://admin:phuonganh_secure_password_2024@localhost:27017/?authSource=admin",
        help="MongoDB connection URI"
    )
    parser.add_argument(
        "--db-name",
        default="phuonganh_tts",
        help="Database name"
    )
    
    args = parser.parse_args()
    
    if len(args.password) < 8:
        print("Error: Password must be at least 8 characters long")
        sys.exit(1)
    
    print(f"Creating admin user: {args.email}")
    
    result = asyncio.run(create_admin_user(
        mongodb_uri=args.mongodb_uri,
        db_name=args.db_name,
        email=args.email,
        password=args.password,
        username=args.username
    ))
    
    if "error" in result:
        print(f"Error: {result['error']}")
        sys.exit(1)
    
    print("\n" + "="*50)
    print("Admin user created successfully!")
    print("="*50)
    print(f"Email:    {result['email']}")
    print(f"Username: {result['username']}")
    print(f"Role:     {result['role']}")
    print(f"Plan:     {result['subscription_plan']}")
    print(f"User ID:  {result['id']}")
    print("="*50)
    print("\nYou can now login with these credentials.")


if __name__ == "__main__":
    main()
