# LumiPly Server

FastAPI 기반 이미지 relighting 서버

## 설치

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

**⚠️ 중요:** `COLAB_WEBHOOK_URL`은 반드시 설정해야 합니다!

## 실행

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

또는 환경 변수의 포트 사용:

```bash
uvicorn main:app --reload --host $FASTAPI_HOST --port $FASTAPI_PORT
```

## API 엔드포인트

### `POST /api/upload`

이미지 업로드 및 처리 시작

**Request:**

- `image`: 업로드할 이미지 파일 (multipart/form-data)

**Response:**

```json
{
  "success": true,
  "job_id": "uuid-string",
  "message": "이미지 업로드 완료. 처리 중입니다."
}
```

### `GET /api/status/{job_id}`

작업 상태 조회

**Response:**

```json
{
  "status": "processing",
  "progress": 50,
  "message": "처리 중..."
}
```

### `POST /api/callback/{job_id}`

Colab 처리 완료 콜백 (내부용)

### `GET /api/test-colab`

Colab 서버 연결 테스트

### `GET /health`

헬스 체크

### `GET /`

서버 정보 조회

## 개발

### 디렉토리 구조

```
lumiply-server/
├── main.py              # FastAPI 애플리케이션
├── requirements.txt     # Python 의존성
├── .env                 # 환경 변수 (gitignore에 포함)
├── .gitignore          # Git 제외 파일
├── uploads/            # 업로드된 이미지 (자동 생성)
└── results/            # 처리 결과 이미지 (자동 생성)
```

### 환경 변수 설명

| 변수                | 설명                    | 기본값                  |
| ------------------- | ----------------------- | ----------------------- |
| `COLAB_WEBHOOK_URL` | Colab ngrok URL (필수)  | 없음                    |
| `FASTAPI_BASE_URL`  | FastAPI 서버 URL        | `http://localhost:8000` |
| `CORS_ORIGINS`      | CORS 허용 도메인        | `http://localhost:3000` |
| `UPLOAD_DIR`        | 업로드 디렉토리         | `uploads`               |
| `RESULTS_DIR`       | 결과 디렉토리           | `results`               |
| `COLAB_TIMEOUT`     | Colab 요청 타임아웃(초) | `300`                   |
| `LOG_LEVEL`         | 로그 레벨               | `INFO`                  |

## 트러블슈팅

### "COLAB_WEBHOOK_URL 환경 변수가 설정되지 않았습니다" 오류

- `.env` 파일을 생성하고 `COLAB_WEBHOOK_URL`을 설정하세요.

### "Colab 서버에 연결할 수 없습니다" 오류

- Colab의 ngrok URL이 유효한지 확인하세요.
- `/api/test-colab` 엔드포인트로 연결을 테스트하세요.

### CORS 오류

- `.env` 파일의 `CORS_ORIGINS`에 프론트엔드 URL을 추가하세요.
