// ===========================================
// PhuongAnh-TTS - MongoDB Initialization Script
// ===========================================
// This script runs automatically when MongoDB container starts for the first time
// It creates the database user, collections, and initial indexes
// ===========================================

print("===========================================");
print(" PhuongAnh-TTS MongoDB Initialization");
print("===========================================");

// Switch to main database
db = db.getSiblingDB('phuonganh_tts');

// ===========================================
// 1. Create Application User
// ===========================================
const appUser = "phuonganh_app";
const appUserPassword = "phuonganh_app_password_2024";

try {
    db.createUser({
        user: appUser,
        pwd: appUserPassword,
        roles: [
            { role: "readWrite", db: "phuonganh_tts" },
            { role: "dbAdmin", db: "phuonganh_tts" }
        ]
    });
    print("✓ Created application user: " + appUser);
} catch (e) {
    if (e.code === 51013) {
        print("→ User " + appUser + " already exists, skipping...");
    } else {
        print("✗ Error creating user: " + e.message);
    }
}

// ===========================================
// 2. Create Collections with Validators
// ===========================================

// --- Users Collection ---
db.createCollection("users", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["email", "password_hash", "created_at", "updated_at"],
            properties: {
                email: {
                    bsonType: "string",
                    pattern: "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
                },
                password_hash: { bsonType: "string" },
                username: { bsonType: "string" },
                phone: { bsonType: "string" },
                subscription_plan: {
                    enum: ["free", "plus", "pro"],
                    default: "free"
                },
                subscription_expires_at: { bsonType: "date" },
                subscription_status: {
                    enum: ["active", "expired", "cancelled", "trial"],
                    default: "active"
                },
                is_verified: { bsonType: "bool", default: false },
                verification_token: { bsonType: "string" },
                last_login: { bsonType: "date" },
                created_at: { bsonType: "date" },
                updated_at: { bsonType: "date" }
            }
        }
    }
});
print("✓ Created collection: users");

// --- Audio Files Collection ---
db.createCollection("audio_files", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["user_id", "filename", "filepath", "filesize", "text_input", "voice_id", "created_at"],
            properties: {
                user_id: { bsonType: "objectId" },
                filename: { bsonType: "string" },
                filepath: { bsonType: "string" },
                filesize: { bsonType: "number" },
                duration: { bsonType: "number" },
                text_input: { bsonType: "string" },
                voice_id: { bsonType: "string" },
                is_watermarked: { bsonType: "bool", default: false },
                download_count: { bsonType: "number", default: 0 },
                created_at: { bsonType: "date" }
            }
        }
    }
});
print("✓ Created collection: audio_files");

// --- Usage Logs Collection ---
db.createCollection("usage_logs", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["user_id", "action", "timestamp"],
            properties: {
                user_id: { bsonType: "objectId" },
                action: {
                    enum: ["tts_generate", "download", "api_call", "register", "login", "upgrade"]
                },
                characters_used: { bsonType: "number" },
                audio_id: { bsonType: "objectId" },
                timestamp: { bsonType: "date" },
                metadata: { bsonType: "object" }
            }
        }
    }
});
print("✓ Created collection: usage_logs");

// --- Subscriptions Collection ---
db.createCollection("subscriptions", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["user_id", "plan", "started_at"],
            properties: {
                user_id: { bsonType: "objectId" },
                plan: { enum: ["free", "plus", "pro"] },
                started_at: { bsonType: "date" },
                expires_at: { bsonType: "date" },
                auto_renew: { bsonType: "bool", default: false },
                payment_history: { bsonType: "array" },
                status: { enum: ["active", "expired", "cancelled"] }
            }
        }
    }
});
print("✓ Created collection: subscriptions");

// --- API Keys Collection ---
db.createCollection("api_keys", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["user_id", "api_key", "created_at"],
            properties: {
                user_id: { bsonType: "objectId" },
                api_key: { bsonType: "string" },
                api_secret_hash: { bsonType: "string" },
                name: { bsonType: "string" },
                permissions: { bsonType: "array" },
                rate_limit: { bsonType: "number" },
                is_active: { bsonType: "bool", default: true },
                last_used: { bsonType: "date" },
                created_at: { bsonType: "date" }
            }
        }
    }
});
print("✓ Created collection: api_keys");

// --- Sessions Collection (for refresh tokens) ---
db.createCollection("sessions", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["user_id", "refresh_token_hash", "created_at", "expires_at"],
            properties: {
                user_id: { bsonType: "objectId" },
                refresh_token_hash: { bsonType: "string" },
                user_agent: { bsonType: "string" },
                ip_address: { bsonType: "string" },
                created_at: { bsonType: "date" },
                expires_at: { bsonType: "date" },
                is_revoked: { bsonType: "bool", default: false }
            }
        }
    }
});
print("✓ Created collection: sessions");

// ===========================================
// 3. Create Indexes
// ===========================================

// Users indexes
db.users.createIndex({ "email": 1 }, { unique: true, background: true });
db.users.createIndex({ "username": 1 }, { sparse: true, background: true });
db.users.createIndex({ "verification_token": 1 }, { sparse: true, background: true });
db.users.createIndex({ "subscription_plan": 1, "subscription_status": 1 }, { background: true });
db.users.createIndex({ "created_at": -1 }, { background: true });
print("✓ Created indexes on: users");

// Audio files indexes
db.audio_files.createIndex({ "user_id": 1, "created_at": -1 }, { background: true });
db.audio_files.createIndex({ "user_id": 1, "_id": 1 }, { background: true });
db.audio_files.createIndex({ "created_at": -1 }, { background: true });
print("✓ Created indexes on: audio_files");

// Usage logs indexes
db.usage_logs.createIndex({ "user_id": 1, "timestamp": -1 }, { background: true });
db.usage_logs.createIndex({ "timestamp": -1 }, { background: true });
db.usage_logs.createIndex({ "action": 1, "timestamp": -1 }, { background: true });
print("✓ Created indexes on: usage_logs");

// Subscriptions indexes
db.subscriptions.createIndex({ "user_id": 1, "started_at": -1 }, { background: true });
db.subscriptions.createIndex({ "expires_at": 1 }, { sparse: true, background: true });
print("✓ Created indexes on: subscriptions");

// API keys indexes
db.api_keys.createIndex({ "api_key": 1 }, { unique: true, background: true });
db.api_keys.createIndex({ "user_id": 1 }, { background: true });
print("✓ Created indexes on: api_keys");

// Sessions indexes
db.sessions.createIndex({ "user_id": 1, "created_at": -1 }, { background: true });
db.sessions.createIndex({ "refresh_token_hash": 1 }, { sparse: true, background: true });
db.sessions.createIndex({ "expires_at": 1 }, { expireAfterSeconds: 0, background: true });
print("✓ Created indexes on: sessions");

// ===========================================
// 4. Create TTL Index for auto-delete old data
// ===========================================

// Auto-delete usage logs after 90 days
db.usage_logs.createIndex(
    { "timestamp": 1 },
    { expireAfterSeconds: 7776000, background: true }
);
print("✓ Created TTL index on: usage_logs (expires after 90 days)");

// Auto-delete expired sessions
db.sessions.createIndex(
    { "expires_at": 1 },
    { expireAfterSeconds: 0, background: true }
);
print("✓ Created TTL index on: sessions (auto-delete expired)");

// ===========================================
// 5. Insert Default Admin User (for testing)
// ===========================================
const adminEmail = "admin@phuonganh.local";
const adminPasswordHash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.FRGYeGGZF6cOOy"; // "admin123"

try {
    db.users.insertOne({
        email: adminEmail,
        password_hash: adminPasswordHash,
        username: "admin",
        subscription_plan: "pro",
        subscription_status: "active",
        subscription_expires_at: new Date("2099-12-31"),
        is_verified: true,
        created_at: new Date(),
        updated_at: new Date()
    });
    print("✓ Created admin user: " + adminEmail);
} catch (e) {
    if (e.code === 11000) {
        print("→ Admin user already exists, skipping...");
    } else {
        print("✗ Error creating admin: " + e.message);
    }
}

// ===========================================
// 6. Create Default Subscription Plans
// ===========================================
const plansCollection = db.getSiblingDB('phuonganh_tts').subscriptions_plans;

plansCollection.deleteMany({});
plansCollection.insertMany([
    {
        _id: "free",
        name: "Free",
        description: "Dùng thử với giới hạn cơ bản",
        price_monthly: 0,
        price_yearly: 0,
        features: {
            daily_audio_limit: 10,
            monthly_chars_limit: 10000,
            max_text_length: 500,
            max_audio_duration: 30,
            watermark: true,
            voice_cloning: false,
            api_access: false,
            streaming: false,
            batch_processing: false,
            priority_support: false
        },
        permissions: [
            "tts:generate",
            "tts:preview"
        ],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        _id: "plus",
        name: "Plus",
        description: "Gói phổ biến cho người dùng thường xuyên",
        price_monthly: 199000,
        price_yearly: 1990000,
        features: {
            daily_audio_limit: 100,
            monthly_chars_limit: 100000,
            max_text_length: 2000,
            max_audio_duration: 120,
            watermark: false,
            voice_cloning: true,
            api_access: true,
            streaming: true,
            batch_processing: false,
            priority_support: true
        },
        permissions: [
            "tts:generate",
            "tts:preview",
            "tts:download",
            "voice:clone",
            "api:access",
            "streaming:enable"
        ],
        created_at: new Date(),
        updated_at: new Date()
    },
    {
        _id: "pro",
        name: "Pro",
        description: "Gói đầy đủ cho doanh nghiệp",
        price_monthly: 499000,
        price_yearly: 4990000,
        features: {
            daily_audio_limit: -1, // unlimited
            monthly_chars_limit: 500000,
            max_text_length: 10000,
            max_audio_duration: 600,
            watermark: false,
            voice_cloning: true,
            api_access: true,
            streaming: true,
            batch_processing: true,
            priority_support: true
        },
        permissions: [
            "tts:generate",
            "tts:preview",
            "tts:download",
            "voice:clone",
            "api:access",
            "streaming:enable",
            "batch:process",
            "admin:support"
        ],
        created_at: new Date(),
        updated_at: new Date()
    }
]);
print("✓ Created subscription plans: free, plus, pro");

// ===========================================
// 7. Create TTL for temp files tracking
// ===========================================
db.temp_files.createCollection("temp_files", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["filepath", "expires_at"],
            properties: {
                filepath: { bsonType: "string" },
                user_id: { bsonType: "objectId" },
                expires_at: { bsonType: "date" },
                created_at: { bsonType: "date" }
            }
        }
    }
});

db.temp_files.createIndex(
    { "expires_at": 1 },
    { expireAfterSeconds: 0, background: true }
);
print("✓ Created temp_files collection with TTL");

// ===========================================
// 8. Final Summary
// ===========================================
print("");
print("===========================================");
print(" MongoDB Initialization Complete!");
print("===========================================");
print("");
print("Database: phuonganh_tts");
print("App User: " + appUser);
print("");
print("Collections created:");
print("  - users");
print("  - audio_files");
print("  - usage_logs");
print("  - subscriptions");
print("  - api_keys");
print("  - sessions");
print("  - temp_files");
print("  - subscriptions_plans");
print("");
print("Connection string:");
print("  mongodb://" + appUser + ":" + appUserPassword + "@mongodb:27017/phuonganh_tts");
print("");
print("Mongo Express (Web Admin):");
print("  http://localhost:8081");
print("  Username: admin");
print("  Password: " + appUserPassword);
print("===========================================");
