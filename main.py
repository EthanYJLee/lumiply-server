# 서버 시작: uvicorn main:app --reload --host 0.0.0.0 --port 8000

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, Body, Response
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
    logger.error("COLAB_WEBHOOK_URL 환경 변수가 설정되지 않았습니다!")
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

logger.info(f"환경 설정 로드 완료:")
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
    """
    업로드된 합성 이미지를 디스크에 저장하고 Colab 쪽으로의 처리 작업을 비동기로 시작합니다.

    Parameters
    ----------
    image : UploadFile
        클라이언트에서 전송한 합성 입력 이미지 파일.
    background_tasks : BackgroundTasks, optional
        FastAPI 백그라운드 작업 큐. 주입되지 않은 경우 asyncio.create_task 로 직접 작업을 생성합니다.

    Returns
    -------
    dict
        success 플래그, 생성된 job_id, 사용자 안내용 message 를 포함하는 JSON 응답.

    Notes
    -----
    - 실제 색상별 생성 처리(send_to_colab)는 비동기로 수행되며, 상태 조회는 /api/status/{job_id} 로 합니다.
    """
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
        
        # USE_DEMO = os.getenv("USE_DEMO", "false").lower() == "true"
        USE_DEMO = False

        if USE_DEMO:
            if background_tasks is not None:
                background_tasks.add_task(simulate_demo_processing, job_id, file_path)
            else:
                asyncio.create_task(simulate_demo_processing(job_id, file_path))
        else:
            print('================= send_to_colab =================')
            if background_tasks is not None:
                background_tasks.add_task(send_to_colab, job_id, file_path)
            else:
                asyncio.create_task(send_to_colab(job_id, file_path))
        
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
    실제 Colab 연동 없이, 미리 준비된 샘플 이미지를 사용해 처리 과정을 흉내내는 데모용 시뮬레이터입니다.

    동작 개요
    --------
    1. 5초 동안 대기하여 처리 지연을 에뮬레이션합니다.
    2. 업로드된 입력 이미지를 results 디렉토리로 복사하여 input_image_url 로 노출합니다.
    3. sample_outputs 디렉토리의 색상별 샘플 이미지 경로를 job_status[job_id]["result"]["images"] 에 매핑합니다.

    Parameters
    ----------
    job_id : str
        업로드 단계에서 생성된 작업 ID.
    file_path : str
        업로드된 합성 입력 이미지의 서버 내 경로.
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
        logger.error(f"[{job_id}] {error_msg}", exc_info=True)
        job_status[job_id]["status"] = "failed"
        job_status[job_id]["error"] = error_msg
        job_status[job_id]["message"] = error_msg

async def send_to_colab(job_id: str, file_path: str):
    """
    업로드된 이미지를 Google Colab 인퍼런스 엔진으로 전송하고, 7개 색상을 순차적으로 생성합니다.

    동작 개요
    --------
    1. 색상 시퀀스(white → purple)에 대해 동일한 입력 이미지를 매번 전송합니다.
    2. 각 색상 처리 결과를 수신할 때마다 job_status[job_id]["result"]["images"] 에 누적 저장하여
       프론트엔드가 부분 결과를 단계적으로 사용할 수 있게 합니다.
    3. HTTP 오류, 타임아웃, 연결 오류가 발생하면 job_status 를 "failed" 로 설정하고 상세 메시지를 남깁니다.

    Parameters
    ----------
    job_id : str
        업로드 단계에서 생성된 작업 ID.
    file_path : str
        업로드된 합성 입력 이미지의 서버 내 경로.
    """
    try:
        # 0% → 10%: 업로드 및 Colab 전송 준비 완료
        job_status[job_id]["status"] = "processing"
        job_status[job_id]["message"] = "이미지를 Colab으로 전송 중..."
        job_status[job_id]["progress"] = 0

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
            "User-Agent": "FastAPI-Client/1.0",  # User-Agent 설정
        }

        # 색상 처리 순서 및 한글 라벨
        color_sequence = [
            ("white", "흰색"),
            ("red", "빨강"),
            ("orange", "주황"),
            ("yellow", "노랑"),
            ("green", "초록"),
            ("blue", "파랑"),
            ("purple", "보라"),
        ]

        # 7개 색상 결과를 누적할 맵
        aggregated_images: Dict[str, str] = {}
        input_image_url: Optional[str] = None

        async with httpx.AsyncClient(timeout=COLAB_TIMEOUT, headers=headers) as client:
            for idx, (color_key, color_label) in enumerate(color_sequence):
                # 전송 완료 기준으로 10% 부여
                base_progress = 10 + idx * 10
                job_status[job_id]["message"] = f"{color_label} 색상 생성 중..."
                job_status[job_id]["progress"] = base_progress

                logger.info(f"[{job_id}] ---- {color_key} 색상 요청 시작 ({base_progress}%) ----\n")

                # 매 색상마다 동일한 입력 이미지를 전송
                with open(file_path, "rb") as f:
                    files = {"image": (os.path.basename(file_path), f, "image/png")}
                    data = {
                        "job_id": job_id,
                        # 현재 구조에서는 callback_url 을 사용하지 않으므로 빈 값 전달
                        "callback_url": "",
                        # Colab 에게 단일 색상만 처리하도록 전달
                        "color": color_key,
                    }

                    try:
                        response = await client.post(
                            COLAB_WEBHOOK_URL,
                            files=files,
                            data=data,
                        )

                        logger.info(f"[{job_id}] [{color_key}] Colab 응답 수신 - 상태 코드: {response.status_code}\n")
                        logger.info(f"[{job_id}] [{color_key}] 응답 헤더: {dict(response.headers)}\n")
                        logger.info(f"[{job_id}] [{color_key}] 응답 본문: {response.text[:500]}")

                        if response.status_code != 200:
                            error_msg = f"Colab 처리 실패 ({color_key}): {response.status_code} - {response.text}"
                            logger.error(f"[{job_id}] {error_msg}")
                            job_status[job_id]["status"] = "failed"
                            job_status[job_id]["error"] = error_msg
                            job_status[job_id]["message"] = f"{color_label} 색상 처리 실패: {response.status_code}"
                            return

                        raw = response.json()
                        logger.info(f"[{job_id}] [{color_key}] Colab 처리 성공: {raw}")

                        inner_result = raw.get("result") if isinstance(raw, dict) else None
                        if not inner_result or not isinstance(inner_result, dict):
                            error_msg = f"Colab 응답 형식 오류 ({color_key}): result 필드가 없습니다."
                            logger.error(f"[{job_id}] {error_msg}")
                            job_status[job_id]["status"] = "failed"
                            job_status[job_id]["error"] = error_msg
                            job_status[job_id]["message"] = f"{color_label} 색상 처리 중 응답 형식 오류"
                            return

                        # 최초 응답에서 input_image_url 을 한 번만 확보
                        if input_image_url is None:
                            input_image_url = inner_result.get("input_image_url")

                        # 이번 색상의 결과 이미지 URL 추출
                        images_map = inner_result.get("images", {})
                        image_url: Optional[str] = None
                        if isinstance(images_map, dict):
                            image_url = images_map.get(color_key)
                        if not image_url:
                            # 단일 색상용으로 image_url 이 있을 수도 있음
                            image_url = inner_result.get("image_url")

                        if not image_url:
                            error_msg = f"Colab 응답에 {color_key} 색상 결과 URL 이 없습니다."
                            logger.error(f"[{job_id}] {error_msg}")
                            job_status[job_id]["status"] = "failed"
                            job_status[job_id]["error"] = error_msg
                            job_status[job_id]["message"] = f"{color_label} 색상 결과 URL 없음"
                            return

                        # 누적 맵에 반영
                        aggregated_images[color_key] = image_url

                        # 부분 결과를 job_status 에 바로 반영하여 프론트가 색상별로 점진적으로 표시할 수 있도록
                        prev_result = job_status[job_id].get("result") or {}
                        prev_images = dict(prev_result.get("images") or {})
                        prev_images[color_key] = image_url
                        job_status[job_id]["result"] = {
                            "images": prev_images,
                            "input_image_url": input_image_url,
                        }

                        # 해당 색상 처리 완료 시점: +10%
                        completed_progress = 10 + (idx + 1) * 10
                        job_status[job_id]["progress"] = completed_progress
                        job_status[job_id]["message"] = f"{color_label} 색상 생성 완료 ({completed_progress}%)"

                    except httpx.HTTPStatusError as e:
                        logger.error(f"[{job_id}] [{color_key}] HTTP 상태 오류: {e.response.status_code}")
                        logger.error(f"[{job_id}] [{color_key}] 응답 내용: {e.response.text}")
                        raise
                    except httpx.RequestError as e:
                        logger.error(f"[{job_id}] [{color_key}] 요청 오류: {str(e)}")
                        raise

        # 모든 색상 처리 완료 → 100%
        job_status[job_id]["status"] = "completed"
        job_status[job_id]["progress"] = 100
        job_status[job_id]["message"] = "모든 색상 이미지 생성이 완료되었습니다."
        # 최종 결과는 누적 맵을 기준으로 한 번 더 덮어써 정합성을 보장
        job_status[job_id]["result"] = {
            "images": aggregated_images,
            "input_image_url": input_image_url,
        }
                    
    except httpx.TimeoutException:
        error_msg = f"Colab 서버 응답 시간 초과 ({int(COLAB_TIMEOUT)}초)"
        logger.error(f"[{job_id}] {error_msg}")
        job_status[job_id]["status"] = "failed"
        job_status[job_id]["error"] = error_msg
        job_status[job_id]["message"] = "처리 시간이 초과되었습니다."
    except httpx.ConnectError as e:
        error_msg = f"Colab 서버 연결 실패: {str(e)}"
        logger.error(f"[{job_id}] {error_msg}")
        job_status[job_id]["status"] = "failed"
        job_status[job_id]["error"] = error_msg
        job_status[job_id]["message"] = "Colab 서버에 연결할 수 없습니다. URL을 확인하세요."
    except httpx.RequestError as e:
        error_msg = f"Colab 서버 요청 오류: {str(e)}"
        logger.error(f"[{job_id}] {error_msg}")
        job_status[job_id]["status"] = "failed"
        job_status[job_id]["error"] = error_msg
        job_status[job_id]["message"] = "Colab 서버 요청 중 오류가 발생했습니다."
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[{job_id}] 처리 오류: {error_msg}", exc_info=True)
        job_status[job_id]["status"] = "failed"
        job_status[job_id]["error"] = error_msg
        job_status[job_id]["message"] = f"처리 중 오류가 발생했습니다: {error_msg}"


@app.get("/api/download_image")
async def download_image(path: str, filename: Optional[str] = None):
  """
  프론트엔드에서 전달한 이미지 경로를 기반으로 안전하게 파일 다운로드를 제공합니다.

  Parameters
  ----------
  path : str
      다운로드할 이미지의 경로. 전체 URL 또는 `/sample_outputs/...`, `/results/...` 형태 모두 허용합니다.
  filename : str, optional
      브라우저에 노출할 다운로드 파일명. 지정하지 않으면 원본 파일명을 그대로 사용합니다.

  동작 방식
  --------
  - 외부 URL(ngrok 등)인 경우: 서버가 직접 이미지를 GET 해서 Response 로 프록시(CORS 우회).
  - 로컬 정적 경로인 경우: SAMPLE_OUTPUTS_DIR / RESULTS_DIR 내 파일만 허용하여 FileResponse 로 반환.

  Raises
  ------
  HTTPException
      - 400: 허용되지 않은 경로 패턴인 경우
      - 404: 파일을 찾을 수 없는 경우
      - 5xx: 외부 URL 프록시 중 예외가 발생한 경우
  """
  parsed = urlparse(path)
  
  # 외부 URL인 경우 (ngrok 등) 서버에서 프록시
  if parsed.scheme in ("http", "https") and parsed.netloc:
      try:
          async with httpx.AsyncClient(timeout=60.0) as client:
              # ngrok 브라우저 경고 우회를 위한 헤더 추가
              headers = {"ngrok-skip-browser-warning": "true"}
              response = await client.get(path, headers=headers)
              response.raise_for_status()
              
              # Content-Type 추출
              content_type = response.headers.get("content-type", "application/octet-stream")
              
              # 파일명 결정
              download_name = filename or os.path.basename(parsed.path) or "download"
              
              return Response(
                  content=response.content,
                  media_type=content_type,
                  headers={
                      "Content-Disposition": f'attachment; filename="{download_name}"'
                  }
              )
      except httpx.HTTPStatusError as e:
          raise HTTPException(status_code=e.response.status_code, detail=f"외부 이미지 다운로드 실패: {e}")
      except Exception as e:
          raise HTTPException(status_code=500, detail=f"이미지 프록시 중 오류: {str(e)}")
  
  # 로컬 파일 경로인 경우
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
    """
    특정 job_id 에 대한 현재 처리 상태를 조회합니다.

    Parameters
    ----------
    job_id : str
        조회할 작업 ID.

    Returns
    -------
    dict
        - status, progress, message, result, error(옵션) 필드를 포함한 작업 상태 객체.

    Notes
    -----
    - 존재하지 않는 job_id 인 경우 404 JSON 응답을 반환합니다.
    """
    if job_id not in job_status:
        return JSONResponse(
            status_code=404,
            content={"error": "작업을 찾을 수 없습니다."}
        )
    return job_status[job_id]

@app.post("/api/callback/{job_id}")
async def colab_callback(job_id: str, payload: dict = Body(...)):
    try:
        logger.info(f"[{job_id}] ========== 콜백 수신 ==========")
        logger.info(f"[{job_id}] 콜백 데이터: {payload}")

        if job_id not in job_status:
            logger.warning(f"[{job_id}] 존재하지 않는 작업 ID")
            return JSONResponse(status_code=404, content={"error": "작업을 찾을 수 없습니다."})

        status_value = payload.get("status", "completed")
        message = payload.get("message") or "이미지 생성이 완료되었습니다."
        raw_result = payload.get("result") or {}

        images = raw_result.get("images", {})              # 색상별 결과 URL 맵 (이미 절대 URL이면 그대로)
        input_image_url = raw_result.get("input_image_url")  # 좌측 인풋 이미지 URL

        # 상태 업데이트
        job_status[job_id]["status"] = status_value
        job_status[job_id]["progress"] = 100
        job_status[job_id]["message"] = message
        job_status[job_id]["result"] = {
            "images": images,
            "input_image_url": input_image_url,
        }

        # 에러 포함 시 상태 덮어쓰기
        if "error" in payload:
            job_status[job_id]["error"] = payload["error"]
            job_status[job_id]["status"] = "failed"

        logger.info(f"[{job_id}] 콜백 처리 완료")
        return {"success": True, "job_id": job_id}

    except Exception as e:
        logger.error(f"[{job_id}] 콜백 처리 오류: {str(e)}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

@app.get("/")
async def root():
    """
    간단한 루트 엔드포인트로, 서버가 정상적으로 기동되었는지와 주요 환경 설정을 확인할 수 있습니다.

    Returns
    -------
    dict
        서버 상태 메시지와 현재 사용 중인 Colab Webhook URL, CORS 설정, 타임아웃 값.
    """
    return {
        "message": "FastAPI 서버가 실행 중입니다.",
        "colab_webhook_url": COLAB_WEBHOOK_URL,
        "cors_origins": cors_origins,
        "timeout": f"{int(COLAB_TIMEOUT)}초"
    }

@app.get("/health")
async def health():
    """
    모니터링 및 로드밸런서용 헬스 체크 엔드포인트입니다.

    Returns
    -------
    dict
        {"status": "healthy"} 형태의 단순 응답.
    """
    return {"status": "healthy"}

# Colab 연결 테스트 엔드포인트 (디버깅용)
@app.get("/api/test-colab")
async def test_colab():
    """
    현재 설정된 COLAB_WEBHOOK_URL 을 기준으로 Colab 서버와의 연결을 사전에 검증하기 위한 엔드포인트입니다.

    Returns
    -------
    dict
        - success: bool
        - status_code / response: health 체크 성공 시 응답 코드 및 내용
        - error: 실패 시 예외 메시지
    """
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