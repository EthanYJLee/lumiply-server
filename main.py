# 서버 시작: uvicorn main:app --reload --host 0.0.0.0 --port 8000

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import httpx
from fastapi import HTTPException
import uuid
import os
from typing import Dict, Optional, List
import json
import logging
import asyncio
import base64
import shutil
from urllib.parse import urlparse

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

# 샘플 출력 디렉토리 (데모용 색상별 결과 이미지)
SAMPLE_OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "sample_outputs")

# 결과 이미지 정적 서빙
app.mount("/results", StaticFiles(directory=RESULTS_DIR), name="results")
if os.path.isdir(SAMPLE_OUTPUTS_DIR):
    app.mount("/sample_outputs", StaticFiles(directory=SAMPLE_OUTPUTS_DIR), name="sample_outputs")

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
        # 데모 모드: 실제 Colab 통신 대신 로컬에서 처리 시뮬레이션
        if background_tasks is not None:
            background_tasks.add_task(simulate_demo_processing, job_id, file_path)
        else:
            # BackgroundTasks 주입이 안 된 경우를 대비한 fallback
            asyncio.create_task(simulate_demo_processing(job_id, file_path))
        
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


async def simulate_demo_processing(job_id: str, file_path: str):
    """
    데모용 처리 시뮬레이션:
    - 5초 대기 후
    - sample_outputs 디렉토리의 색상별 샘플 이미지를 그대로 반환
      (white/red/orange/yellow/green/blue/purple 총 7장)
    """
    try:
        logger.info(f"[{job_id}] 데모 처리 시작 (simulate_demo_processing)")
        job_status[job_id]["status"] = "processing"
        job_status[job_id]["message"] = "데모 모델이 이미지를 처리 중입니다..."
        job_status[job_id]["progress"] = 30

        await asyncio.sleep(5)

        # 업로드된 합성 입력 이미지를 결과 디렉토리로 복사하여, 히스토리에서 안정적으로 참조할 수 있도록 함
        input_ext = os.path.splitext(file_path)[1] or ".png"
        input_result_filename = f"{job_id}_input{input_ext}"
        input_result_path = os.path.join(RESULTS_DIR, input_result_filename)
        try:
            shutil.copyfile(file_path, input_result_path)
            input_image_url = f"/results/{input_result_filename}"
            logger.info(f"[{job_id}] 입력 합성 이미지 복사 완료: {input_result_path} (url={input_image_url})")
        except Exception as copy_err:
            logger.error(f"[{job_id}] 입력 합성 이미지 복사 실패: {copy_err}")
            input_image_url = None

        # 색상별 샘플 이미지 매핑
        color_keys = ["white", "red", "orange", "yellow", "green", "blue", "purple"]
        color_images: Dict[str, Optional[str]] = {}

        for color in color_keys:
            filename = f"output_{color}.jpg"
            src_path = os.path.join(SAMPLE_OUTPUTS_DIR, filename)
            if os.path.exists(src_path):
                # StaticFiles 로 /sample_outputs 에 마운트되어 있으므로 복사 없이 URL 만 제공
                url_path = f"/sample_outputs/{filename}"
                color_images[color] = url_path
                logger.info(f"[{job_id}] 데모 샘플 이미지 매핑: {color} -> {url_path}")
            else:
                logger.warning(f"[{job_id}] 샘플 이미지 없음: {src_path}")
                color_images[color] = None

        result_payload = {
            # 색상별 결과 이미지 URL (상대 경로)
            "images": color_images,
            # 프론트엔드에서 좌측 인풋으로 사용할 합성 입력 이미지 URL (RESULTS_DIR 기반)
            "input_image_url": input_image_url,
            # 참고용으로 입력 이미지 서버 경로도 함께 반환
            "original_upload_path": file_path,
        }

        job_status[job_id]["status"] = "completed"
        job_status[job_id]["progress"] = 100
        job_status[job_id]["result"] = result_payload
        job_status[job_id]["message"] = "데모 이미지 생성이 완료되었습니다."

        logger.info(f"[{job_id}] 데모 처리 완료")
    except Exception as e:
        error_msg = f"데모 처리 중 오류 발생: {str(e)}"
        logger.error(f"[{job_id}] ❌ {error_msg}", exc_info=True)
        job_status[job_id]["status"] = "failed"
        job_status[job_id]["error"] = error_msg
        job_status[job_id]["message"] = error_msg

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


@app.get("/api/download_image")
async def download_image(path: str, filename: Optional[str] = None):
  """
  프론트엔드에서 전달한 이미지 경로를 기반으로 파일 다운로드를 제공
  - path 는 전체 URL 또는 /sample_outputs/... /results/... 형태 모두 허용
  """
  # 전체 URL 이 들어온 경우 path 부분만 추출
  parsed = urlparse(path)
  rel_path = parsed.path if parsed.scheme in ("http", "https") else path

  # 허용된 디렉토리만 처리
  base_dir: Optional[str] = None
  if rel_path.startswith("/sample_outputs/"):
      base_dir = SAMPLE_OUTPUTS_DIR
  elif rel_path.startswith("/results/"):
      base_dir = RESULTS_DIR
  else:
      raise HTTPException(status_code=400, detail="잘못된 파일 경로입니다.")

  file_name = os.path.basename(rel_path)
  file_path = os.path.join(base_dir, file_name)

  if not os.path.exists(file_path):
      raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

  download_name = filename or file_name
  return FileResponse(file_path, filename=download_name)

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
        
        # 기본 상태/메시지 업데이트
        job_status[job_id]["status"] = result.get("status", "completed")
        job_status[job_id]["progress"] = 100
        if "message" in result:
            job_status[job_id]["message"] = result["message"]

        # Colab에서 전달된 결과 처리
        raw_result = result.get("result")
        result_payload: Dict = {}

        if isinstance(raw_result, dict):
            result_payload = dict(raw_result)  # 원본 유지 위해 복사

            # image_base64가 있으면 디코딩해서 결과 파일로 저장
            image_b64 = result_payload.get("image_base64")
            if image_b64:
                try:
                    image_bytes = base64.b64decode(image_b64)
                    result_path = os.path.join(RESULTS_DIR, f"{job_id}.png")
                    with open(result_path, "wb") as f:
                        f.write(image_bytes)

                    image_url = f"/results/{job_id}.png"
                    # 프론트에서 바로 사용할 수 있는 URL을 제공
                    result_payload["image_url"] = image_url
                    # 불필요하게 큰 base64 문자열은 상태에서 제거 (옵션)
                    result_payload.pop("image_base64", None)

                    logger.info(f"[{job_id}] 결과 이미지 저장 완료: {result_path} (url={image_url})")
                except Exception as e:
                    logger.error(f"[{job_id}] 결과 이미지 저장 실패: {str(e)}", exc_info=True)

        if result_payload:
            job_status[job_id]["result"] = result_payload

        # 에러가 포함된 경우 상태를 failed 로 덮어씀
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