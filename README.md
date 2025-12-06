## LumiPly Server (FastAPI)

React 프론트엔드와 Colab 상의 LumiNet 모델 사이를 연결해 주는 **이미지 조명 생성용 FastAPI 서버**입니다.  
클라이언트에서 업로드한 “방 사진 + 가상 조명” 이미지를 받아 Colab으로 전송하고, 7가지 색상의 결과 이미지를 다시 모아서 프론트로 돌려줍니다.

---

### 1. 전체 구조 개요

- **역할**

  - 클라이언트가 캔버스에서 합성한 이미지를 업로드
  - Google Colab에서 구동 중인 Flask 서버(`/process`)로 이미지를 전달
  - `white, red, orange, yellow, green, blue, purple` 7가지 색상별 결과를 모두 수신
  - 각 색상 결과 URL과 입력 이미지를 하나의 `job` 결과로 모아 `/api/status/{job_id}` 로 제공
  - 진행률(progress)와 상태 메시지를 관리해 프론트의 로딩 UI에 사용

- **주요 구성 요소**
  - `FastAPI` 애플리케이션 (`main.py`)
  - Colab Flask 서버
  - ngrok HTTPS 터널 (Colab → 외부 공개용)
  - 단순 in‑memory `job_status` (demo / PoC 용도)

데이터 플로우 (정상 경로):

1. 프론트에서 조명까지 합성된 PNG를 `/api/upload` 로 전송
2. 서버가 파일을 `UPLOAD_DIR` 에 저장하고 `job_id` 생성
3. 백그라운드에서 `send_to_colab(job_id, file_path)` 실행
4. `send_to_colab` 이 Colab `/process` 를 색상별로 7번 호출 (각각 `color=white`, `red`, …)
5. Colab은 각 색상에 대해 `output_{color}.jpg` 를 생성하고 public URL 을 JSON 으로 반환
6. 서버는 7개의 URL과 `input_image_url` 을 하나로 합쳐 `job_status[job_id].result` 에 저장
7. 프론트는 `/api/status/{job_id}` 를 폴링하면서 진행률과 결과를 가져와 화면에 표시

---

### 2. 디렉터리 구조

```bash
lumiply-server/
├── main.py              # FastAPI 애플리케이션, Colab 연동, job 상태 관리
├── requirements.txt     # Python dependencies
├── README.md
├── .env                 # 환경 변수
├── uploads/             # 업로드된 composite 이미지 (자동 생성)
└── results/             # 데모/입력 이미지 복사본 등
```

---

### 3. 환경 변수 (.env)

프로젝트 루트(`lumiply-server/`)에 `.env` 파일을 두고 아래 값을 설정합니다.

| 변수                | 설명                                                        | 예시 / 기본값                        |
| ------------------- | ----------------------------------------------------------- | ------------------------------------ |
| `COLAB_WEBHOOK_URL` | Colab Flask `/process` 의 public URL (ngrok HTTPS) **필수** | `https://xxx.ngrok-free.dev/process` |
| `FASTAPI_BASE_URL`  | FastAPI 서버의 외부 주소 (callback 사용 시)                 | `http://localhost:8000`              |
| `CORS_ORIGINS`      | 허용할 프론트엔드 origin 리스트 (`,` 로 구분)               | `http://localhost:3000`              |
| `UPLOAD_DIR`        | 업로드 이미지 저장 디렉터리                                 | `uploads`                            |
| `RESULTS_DIR`       | 결과/입력 복사본 저장 디렉터리                              | `results`                            |
| `COLAB_TIMEOUT`     | Colab HTTP 요청 타임아웃(초)                                | `300`                                |
| `LOG_LEVEL`         | 로그 레벨                                                   | `INFO`                               |
| `USE_DEMO`          | 데모 / 실서비스 구분                                        | `true` / `false`                     |

> `COLAB_WEBHOOK_URL` 이 설정되지 않으면 서버 시작 시 바로 예외가 발생합니다.

---

### 4. 로컬 실행 방법

#### 4‑1. 의존성 설치

```bash
cd lumiply-server
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

#### 4‑2. .env 설정

Colab에서 ngrok 설정 셀을 실행하고, 출력된 `/process` URL 을 `.env` 에 넣습니다.

```env
COLAB_WEBHOOK_URL=https://<ngrok-subdomain>.ngrok-free.dev/process
```

#### 4‑3. FastAPI 서버 실행

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

---

### 5. 주요 API 설명

#### `POST /api/upload`

클라이언트에서 합성된 PNG 이미지를 업로드하고, Colab 작업을 시작합니다.

- **Request (multipart/form-data)**
  - `image`: 합성된 PNG 파일
- **Response (예시)**

```json
{
  "success": true,
  "job_id": "c1f0dffe-...",
  "message": "이미지 업로드 완료. 처리 중입니다."
}
```

업로드 직후 `job_status[job_id]` 가 생성되며, `send_to_colab` 가 백그라운드에서 실행됩니다.

#### `GET /api/status/{job_id}`

작업 상태 및 결과 조회. 프론트엔드에서 폴링에 사용합니다.

```json
{
  "status": "processing",
  "progress": 40,
  "message": "orange 색상 생성 완료 (40%)",
  "result": {
    "images": {
      "white": "https://.../output_white.jpg",
      "red": "https://.../output_red.jpg",
      "...": "..."
    },
    "input_image_url": "https://.../off.png"
  }
}
```

#### `GET /api/download_image?path=...&filename=...`

프론트엔드가 현재 선택된 결과 이미지를 **새 탭 없이** 다운로드할 때 사용하는 엔드포인트입니다.

- `path`: `/results/...` 또는 `/sample_outputs/...` 혹은 동일한 것을 가리키는 절대 URL
- `filename`: 브라우저에 제안할 파일 이름

#### `POST /api/callback/{job_id}`

Colab에서 push 방식으로 결과를 보내고 싶을 때 사용할 수 있는 콜백 엔드포인트입니다.  
현재 구조에서는 pull 방식(polling)으로 충분하지만, 추후 확장을 위해 남겨두었습니다.

#### `GET /api/test-colab`

`COLAB_WEBHOOK_URL` 에 연결이 정상인지 빠르게 확인하는 용도의 헬퍼 엔드포인트입니다.

---

### 6. send_to_colab / 진행률 로직

`send_to_colab(job_id, file_path)` 는 다음과 같이 동작합니다.

1. `status = "processing"`, `progress = 0` 으로 초기화
2. 색상 배열 정의:
   ```python
   [("white", "흰색"), ("red", "빨강"), ..., ("purple", "보라")]
   ```
3. 각 색상에 대해 순차적으로 Colab `/process` 호출
   - 요청 body: `image`, `job_id`, `color`
   - 응답이 200이면 해당 색상의 URL 을 `aggregated_images[color]` 에 기록
   - 색상 하나 완료할 때마다 `progress` 를 10%씩 올리며 메시지 갱신
4. 7개 색상이 모두 성공하면:
   - `status = "completed"`
   - `progress = 100`
   - `result.images = aggregated_images`
   - `result.input_image_url` 설정

프론트엔드에서는 이 정보를 바탕으로 **원형 로더 + 텍스트**를 단계적으로 업데이트합니다.

---

### 7. Colab / ngrok 팁

- Colab 노트북
- 셀 순서:
  1. 작업 디렉터리 이동
  2. requirements 설치
  3. 모델/엔진 초기화 (`initialize_engine`, `run_inference_single_image`)
  4. Flask 서버 정의 (`/health`, `/process`)
  5. ngrok 설정 셀 (PUBLIC_URL, process_url 출력)
  6. Flask 서버 실행 (백그라운드 쓰레드)
- 세션을 완전히 끊고 다시 시작할 경우:
  - 위 순서를 다시 실행하고,
  - 새로 출력된 `/process` URL 을 `.env` 의 `COLAB_WEBHOOK_URL` 로 교체 후 FastAPI 재시작

ngrok 관련 에러(`ERR_NGROK_334`)가 날 경우, Colab에서 `ngrok.kill()` 이나 별도의 “Stop Cell”을 통해 기존 터널을 정리한 뒤 다시 시도하면 됩니다.

---

### 8. 트러블슈팅 체크리스트

- 서버 시작 시 **COLAB_WEBHOOK_URL 관련 예외**가 난다면
  - `.env` 에 `COLAB_WEBHOOK_URL` 이 제대로 들어가 있는지,
  - URL 끝에 `/process` 가 붙어 있는지 확인합니다.
- `/api/test-colab` 가 실패한다면
  - Colab 런타임이 살아 있는지,
  - ngrok 셀([Cell 3])이 오류 없이 끝났는지 확인합니다.
- 프론트엔드에서 결과가 안 뜨는 경우
  - FastAPI 로그에 Colab 응답(JSON)이 찍히는지,
  - `status.result.images.white` 같은 키가 실제로 존재하는지 확인합니다.
