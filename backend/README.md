# PhuongAnh-TTS Backend API

## Mô Tả

Backend API cho PhuongAnh-TTS - Vietnamese Text-to-Speech với hệ thống quản lý người dùng và subscription.

## Tính Năng

- **Authentication**: JWT-based với refresh tokens
- **Subscription Tiers**: Free, Plus, Pro
- **Rate Limiting**: Giới hạn usage theo plan
- **Audio Storage**: Lưu trữ và quản lý audio files
- **MongoDB**: Database cho users, audio files, usage logs

## Cấu Trúc

```
backend/
├── api/
│   ├── dependencies/    # FastAPI dependencies
│   └── routes/          # API routes (auth, user, audio)
├── core/
│   ├── config.py       # Settings từ env
│   └── database.py     # MongoDB & Redis connections
├── models/
│   └── schemas/        # Pydantic models
├── services/
│   ├── auth_service.py       # Authentication
│   ├── user_service.py      # User management
│   ├── subscription_service.py # Subscription
│   └── audio_service.py      # Audio storage
├── utils/
│   └── api_client.py   # API client wrapper
├── tests/
├── main.py             # FastAPI app
├── Dockerfile
└── requirements.txt
```

## Docker Deployment

### Development

```bash
# Copy environment file
cp .env.example .env

# Start services
docker-compose up -d

# Check logs
docker-compose logs -f api
```

### Production

```bash
# Edit .env với production values
docker-compose -f docker-compose.prod.yml up -d
```

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Đăng ký tài khoản |
| POST | `/api/auth/login` | Đăng nhập |
| POST | `/api/auth/logout` | Đăng xuất |
| POST | `/api/auth/refresh` | Refresh token |
| POST | `/api/auth/change-password` | Đổi mật khẩu |

### User

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/user/profile` | Lấy thông tin profile |
| PUT | `/api/user/profile` | Cập nhật profile |
| GET | `/api/user/usage` | Xem usage statistics |
| GET | `/api/user/subscription` | Xem subscription |

### Audio

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/audio/voices` | Danh sách giọng |
| POST | `/api/audio/generate` | Tạo audio TTS |
| GET | `/api/audio/list` | Danh sách audio của user |
| DELETE | `/api/audio/{id}` | Xóa audio |
| GET | `/api/audio/{id}/download` | Tải audio |

## Subscription Plans

| Feature | Free | Plus | Pro |
|---------|------|------|-----|
| Audio/ngày | 10 | 100 | Unlimited |
| Ký tự/tháng | 10,000 | 100,000 | 500,000 |
| Max text length | 500 | 2,000 | 10,000 |
| Max audio duration | 30s | 120s | 600s |
| Watermark | ✓ | ✗ | ✗ |
| Voice Cloning | ✗ | ✓ | ✓ |
| API Access | ✗ | ✓ | ✓ |
| Batch Processing | ✗ | ✗ | ✓ |

## API Documentation

Sau khi start server, truy cập:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Environment Variables

Xem `.env.example` để biết các biến môi trường cần thiết.

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run server
python main.py

# Run tests
pytest tests/ -v
```

## License

CC BY-NC 4.0
