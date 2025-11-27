# 서버 시작: uvicorn main:app --reload --host 0.0.0.0 --port 8000

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
import httpx
import uuid
import os
from typing import Dict, Optional, List
import json
import logging

# .env 파일 로드
load_dotenv()

# 로깅 설정
log_level = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

app = FastAPI()

# 환경 변수에서 CORS 설정 로드
cors_origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000")
cors_origins: List[str] = [origin.strip() for origin in cors_origins_str.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 작업 상태 저장소
job_status: Dict[str, dict] = {}

# 환경 변수에서 설정 로드
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
RESULTS_DIR = os.getenv("RESULTS_DIR", "results")
COLAB_WEBHOOK_URL = os.getenv("COLAB_WEBHOOK_URL")
FASTAPI_BASE_URL = os.getenv("FASTAPI_BASE_URL", "http://localhost:8000")
COLAB_TIMEOUT = float(os.getenv("COLAB_TIMEOUT", "300"))

# 필수 환경 변수 확인
if not COLAB_WEBHOOK_URL:
    logger.error("❌ COLAB_WEBHOOK_URL 환경 변수가 설정되지 않았습니다!")
    logger.error("   .env 파일에 COLAB_WEBHOOK_URL을 설정해주세요.")
    raise ValueError("COLAB_WEBHOOK_URL 환경 변수가 필요합니다.")

# 디렉토리 생성
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

logger.info(f"✅ 환경 설정 로드 완료:")
logger.info(f"   - COLAB_WEBHOOK_URL: {COLAB_WEBHOOK_URL}")
logger.info(f"   - FASTAPI_BASE_URL: {FASTAPI_BASE_URL}")
logger.info(f"   - CORS_ORIGINS: {cors_origins}")
logger.info(f"   - UPLOAD_DIR: {UPLOAD_DIR}")
logger.info(f"   - RESULTS_DIR: {RESULTS_DIR}")
logger.info(f"   - COLAB_TIMEOUT: {COLAB_TIMEOUT}초")

@app.post("/api/upload")
async def upload_image(
    image: UploadFile = File(...),
    background_tasks: BackgroundTasks = None
):
    """이미지 업로드 및 처리 작업 시작"""
    try:
        job_id = str(uuid.uuid4())
        logger.info(f"새 작업 시작: {job_id}")
        
        file_path = os.path.join(UPLOAD_DIR, f"{job_id}_{image.filename}")
        contents = await image.read()
        with open(file_path, "wb") as f:
            f.write(contents)
        
        logger.info(f"파일 저장 완료: {file_path} (크기: {len(contents)} bytes)")
        
        job_status[job_id] = {
            "status": "pending",
            "progress": 0,
            "message": "작업이 대기 중입니다."
        }
        
        background_tasks.add_task(send_to_colab, job_id, file_path)
        
        return {
            "success": True,
            "job_id": job_id,
            "message": "이미지 업로드 완료. 처리 중입니다."
        }
        
    except Exception as e:
        logger.error(f"업로드 오류: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

async def send_to_colab(job_id: str, file_path: str):
    """Google Colab으로 이미지 전송 및 처리 요청"""
    try:
        job_status[job_id]["status"] = "processing"
        job_status[job_id]["message"] = "Colab으로 이미지 전송 중..."
        job_status[job_id]["progress"] = 30
        
        logger.info(f"[{job_id}] ========== Colab 전송 시작 ==========")
        logger.info(f"[{job_id}] Colab URL: {COLAB_WEBHOOK_URL}")
        logger.info(f"[{job_id}] 파일 경로: {file_path}")
        
        # 파일 크기 확인
        file_size = os.path.getsize(file_path)
        logger.info(f"[{job_id}] 파일 크기: {file_size} bytes")
        
        # httpx 클라이언트 설정
        # - ngrok 브라우저 경고 우회를 위한 헤더 추가
        headers = {
            "ngrok-skip-browser-warning": "true",  # ngrok 브라우저 경고 우회
            "User-Agent": "FastAPI-Client/1.0"  # User-Agent 설정
        }
        
        async with httpx.AsyncClient(timeout=COLAB_TIMEOUT, headers=headers) as client:
            # 파일 읽기
            with open(file_path, "rb") as f:
                files = {"image": (os.path.basename(file_path), f, "image/png")}
                data = {
                    "job_id": job_id, 
                    "callback_url": f"{FASTAPI_BASE_URL}/api/callback/{job_id}"
                }
                
                logger.info(f"[{job_id}] Callback URL: {data['callback_url']}")
                logger.info(f"[{job_id}] 요청 전송 중...")
                
                try:
                    response = await client.post(
                        COLAB_WEBHOOK_URL,
                        files=files,
                        data=data
                    )
                    
                    logger.info(f"[{job_id}] ========== Colab 응답 수신 ==========")
                    logger.info(f"[{job_id}] 상태 코드: {response.status_code}")
                    logger.info(f"[{job_id}] 응답 헤더: {dict(response.headers)}")
                    logger.info(f"[{job_id}] 응답 본문: {response.text[:500]}")  # 500자만
                    
                    if response.status_code == 200:
                        result = response.json()
                        logger.info(f"[{job_id}] ✅ Colab 처리 성공: {result}")
                        job_status[job_id]["status"] = "completed"
                        job_status[job_id]["progress"] = 100
                        job_status[job_id]["result"] = result
                        job_status[job_id]["message"] = "처리가 완료되었습니다."
                    else:
                        error_msg = f"Colab 처리 실패: {response.status_code} - {response.text}"
                        logger.error(f"[{job_id}] ❌ {error_msg}")
                        job_status[job_id]["status"] = "failed"
                        job_status[job_id]["error"] = error_msg
                        job_status[job_id]["message"] = f"처리 실패: {response.status_code}"
                        
                except httpx.HTTPStatusError as e:
                    logger.error(f"[{job_id}] HTTP 상태 오류: {e.response.status_code}")
                    logger.error(f"[{job_id}] 응답 내용: {e.response.text}")
                    raise
                except httpx.RequestError as e:
                    logger.error(f"[{job_id}] 요청 오류: {str(e)}")
                    raise
                    
    except httpx.TimeoutException:
        error_msg = f"Colab 서버 응답 시간 초과 ({int(COLAB_TIMEOUT)}초)"
        logger.error(f"[{job_id}] ❌ {error_msg}")
        job_status[job_id]["status"] = "failed"
        job_status[job_id]["error"] = error_msg
        job_status[job_id]["message"] = "처리 시간이 초과되었습니다."
    except httpx.ConnectError as e:
        error_msg = f"Colab 서버 연결 실패: {str(e)}"
        logger.error(f"[{job_id}] ❌ {error_msg}")
        job_status[job_id]["status"] = "failed"
        job_status[job_id]["error"] = error_msg
        job_status[job_id]["message"] = "Colab 서버에 연결할 수 없습니다. URL을 확인하세요."
    except httpx.RequestError as e:
        error_msg = f"Colab 서버 요청 오류: {str(e)}"
        logger.error(f"[{job_id}] ❌ {error_msg}")
        job_status[job_id]["status"] = "failed"
        job_status[job_id]["error"] = error_msg
        job_status[job_id]["message"] = "Colab 서버 요청 중 오류가 발생했습니다."
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[{job_id}] ❌ 처리 오류: {error_msg}", exc_info=True)
        job_status[job_id]["status"] = "failed"
        job_status[job_id]["error"] = error_msg
        job_status[job_id]["message"] = f"처리 중 오류가 발생했습니다: {error_msg}"

@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    """작업 상태 조회"""
    if job_id not in job_status:
        return JSONResponse(
            status_code=404,
            content={"error": "작업을 찾을 수 없습니다."}
        )
    return job_status[job_id]

@app.post("/api/callback/{job_id}")
async def colab_callback(job_id: str, result: dict = Body(...)):
    """Colab에서 처리 완료 후 콜백"""
    try:
        logger.info(f"[{job_id}] ========== 콜백 수신 ==========")
        logger.info(f"[{job_id}] 콜백 데이터: {result}")
        
        if job_id not in job_status:
            logger.warning(f"[{job_id}] 존재하지 않는 작업 ID")
            return JSONResponse(
                status_code=404,
                content={"error": "작업을 찾을 수 없습니다."}
            )
        
        job_status[job_id]["status"] = result.get("status", "completed")
        job_status[job_id]["progress"] = 100
        
        if "result" in result:
            job_status[job_id]["result"] = result["result"]
        
        if "message" in result:
            job_status[job_id]["message"] = result["message"]
        
        if "error" in result:
            job_status[job_id]["error"] = result["error"]
            job_status[job_id]["status"] = "failed"
        
        logger.info(f"[{job_id}] ✅ 콜백 처리 완료")
        return {"success": True, "job_id": job_id}
        
    except Exception as e:
        logger.error(f"[{job_id}] ❌ 콜백 처리 오류: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "message": "FastAPI 서버가 실행 중입니다.",
        "colab_webhook_url": COLAB_WEBHOOK_URL,
        "cors_origins": cors_origins,
        "timeout": f"{int(COLAB_TIMEOUT)}초"
    }

@app.get("/health")
async def health():
    """헬스 체크"""
    return {"status": "healthy"}

# Colab 연결 테스트 엔드포인트 (디버깅용)
@app.get("/api/test-colab")
async def test_colab():
    """Colab 서버 연결 테스트"""
    import httpx
    
    try:
        headers = {
            "ngrok-skip-browser-warning": "true",
            "User-Agent": "FastAPI-Client/1.0"
        }
        
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            # Health check 엔드포인트 테스트
            health_url = COLAB_WEBHOOK_URL.replace("/process", "/health")
            logger.info(f"Colab Health Check URL: {health_url}")
            
            response = await client.get(health_url)
            
            return {
                "success": True,
                "status_code": response.status_code,
                "response": response.json() if response.status_code == 200 else response.text
            }
    except Exception as e:
        logger.error(f"Colab 테스트 실패: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }