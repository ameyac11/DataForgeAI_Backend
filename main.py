import os
from pathlib import Path
from fastapi import FastAPI, Query, Depends, HTTPException, UploadFile, File, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from middleware.error_handler import (
    http_exception_handler,
    validation_exception_handler,
    general_exception_handler
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.search_datasets import InternetSearchRequest, InternetSearchResponse, search_datasets 
from api.ai_assistant import KeywordSearchRequest, KeywordSearchResponse, search_keywords, PromptEnhanceRequest, PromptEnhanceResponse, enhance_prompt_api
from api.generate_columns import GenerateColumnsRequest, GenerateColumnsResponse, generate_columns
from api.generate_preview import PreviewRequest, PreviewResponse, generate_preview
from api.sample_datasets import (get_sample_datasets, download_sample_dataset, get_dataset_categories, get_dataset_formats, SampleDatasetsResponse, SAMPLE_DATASETS_DIR)
from api.generate_dataset import DownloadDatasetRequest, DownloadDatasetResponse, generate_dataset
from api.generate_ai_dataset import AiDatasetRequest, AiDatasetResponse, generate_ai_dataset
from api.dataset_analytics import DatasetAnalysisRequest, DatasetAnalysisResponse, analyze_dataset_file
from api.github_ai import get_available_models, POWERFUL_MODEL
from auth.routes import router as auth_router
from auth.routes import get_current_user
from typing import Optional

# Import database initialization
from config.db_init import initialize_database

# Import model limits service for cache warming and anonymous sessions
from services.model_limits import get_model_limits_service

app = FastAPI(
    title="DataNestX API", 
    description="AI-powered dataset generation platform", 
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Initialize database collections and indexes on startup (non-blocking)
import asyncio
from fastapi.concurrency import run_in_threadpool

@app.on_event("startup")
async def startup_event():
    """Initialize MongoDB collections and warm up caches on startup (non-blocking)."""
    loop = asyncio.get_event_loop()
    # Run blocking initializations in a thread pool
    async def init_db():
        try:
            await run_in_threadpool(initialize_database)
        except Exception:
            pass
    async def warmup_cache():
        try:
            service = get_model_limits_service()
            await run_in_threadpool(service.refresh_limits_cache)
        except Exception:
            pass
    # Schedule both tasks concurrently
    await asyncio.gather(init_db(), warmup_cache())

# All backend routes are under /api; auth router keeps its /auth prefix inside /api
app.include_router(auth_router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://datanestx.tech", "https://www.datanestx.tech"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "message": "API is running"}

@app.get("/api/models")
async def get_models(current_user: Optional[dict] = Depends(get_current_user)):
    is_authenticated = current_user is not None
    models = get_available_models(is_authenticated)
    return {"models": models, "is_authenticated": is_authenticated}

@app.post("/api/search_datasets", response_model=InternetSearchResponse)
async def api_search_dataset(request: InternetSearchRequest):
    try:
        response = search_datasets(request.query)
        return InternetSearchResponse(datasets=response)
    except Exception as e:
        print(f"Error in api_search_dataset: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/search_keywords", response_model=KeywordSearchResponse)
async def api_search_keywords(
    request: KeywordSearchRequest,
    response: Response,
    current_user: Optional[dict] = Depends(get_current_user),
    x_anonymous_session: Optional[str] = Header(None)
):
    try:
        if current_user:
            user_id = current_user.get("id")
        else:
            service = get_model_limits_service()
            user_id = service.get_or_create_anonymous_session(x_anonymous_session)
            response.headers["X-Anonymous-Session"] = user_id
        
        keywords = search_keywords(request.query, user_id)
        return KeywordSearchResponse(keywords=keywords)
    except Exception as e:
        print(f"Error in api_search_keywords: {str(e)}")
        return KeywordSearchResponse(keywords=[])

@app.post("/api/enhance_prompt", response_model=PromptEnhanceResponse)
async def api_enhance_prompt(
    request: PromptEnhanceRequest,
    response: Response,
    current_user: Optional[dict] = Depends(get_current_user),
    x_anonymous_session: Optional[str] = Header(None)
):
    try:
        if current_user:
            user_id = current_user.get("id")
        else:
            service = get_model_limits_service()
            user_id = service.get_or_create_anonymous_session(x_anonymous_session)
            response.headers["X-Anonymous-Session"] = user_id
        
        enhanced_prompt = enhance_prompt_api(request.prompt, user_id)
        return PromptEnhanceResponse(
            enhanced_prompt=enhanced_prompt,
            original_prompt=request.prompt
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error in api_enhance_prompt: {str(e)}")
        return PromptEnhanceResponse(
            enhanced_prompt=request.prompt,
            original_prompt=request.prompt
        )

@app.post("/api/generate_columns", response_model=GenerateColumnsResponse)
async def api_generate_columns(
    request: GenerateColumnsRequest,
    response: Response,
    current_user: Optional[dict] = Depends(get_current_user),
    x_anonymous_session: Optional[str] = Header(None)
):
    try:
        if current_user:
            user_id = current_user.get("id")
        else:
            service = get_model_limits_service()
            user_id = service.get_or_create_anonymous_session(x_anonymous_session)
            response.headers["X-Anonymous-Session"] = user_id
        
        result = generate_columns(
            topic=request.topic,
            available_types=request.availableTypes,
            strategy=request.strategy,
            template=request.template,
            user_id=user_id
        )
        return result
    except Exception as e:
        print(f"Error in api_generate_columns: {str(e)}")
        return GenerateColumnsResponse(columns=[])

@app.post("/api/generate_preview", response_model=PreviewResponse)
async def api_generate_preview(
    request: PreviewRequest,
    response: Response,
    current_user: Optional[dict] = Depends(get_current_user),
    x_anonymous_session: Optional[str] = Header(None)
):
    try:
        if current_user:
            user_id = current_user.get("id")
        else:
            service = get_model_limits_service()
            user_id = service.get_or_create_anonymous_session(x_anonymous_session)
            response.headers["X-Anonymous-Session"] = user_id
        
        if request.rows > 100:
            raise HTTPException(status_code=400, detail="Preview limited to 100 rows maximum")
        
        result = generate_preview(
            source=request.source,
            columns=request.columns,
            rows=request.rows,
            format=request.format,
            keyword=request.keyword,
            user_id=user_id
        )
        return PreviewResponse(data=result)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in api_generate_preview: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate preview")

@app.post("/api/generate_dataset")
async def api_generate_dataset(
    request: DownloadDatasetRequest,
    response: Response,
    current_user: Optional[dict] = Depends(get_current_user),
    x_anonymous_session: Optional[str] = Header(None)
):
    try:
        is_authenticated = current_user is not None

        if current_user:
            user_id = current_user.get("id")
        else:
            service = get_model_limits_service()
            user_id = service.get_or_create_anonymous_session(x_anonymous_session)
            response.headers["X-Anonymous-Session"] = user_id
        
        if request.rows > 10000:
            raise HTTPException(status_code=400, detail="Maximum 10,000 rows allowed per dataset")
        
        if len(request.columns) > 50:
            raise HTTPException(status_code=400, detail="Maximum 50 columns allowed per dataset")
        
        result = generate_dataset(
            columns=request.columns,
            rows=request.rows,
            format=request.format,
            source=request.source,
            keyword=request.keyword,
            user_id=user_id,
            model_id=request.model_id,
            is_authenticated=is_authenticated,
        )
        return DownloadDatasetResponse(dataset=result)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in api_generate_dataset: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to generate dataset")

# Endpoint to get/create anonymous session
@app.get("/api/session/anonymous")
async def get_anonymous_session(x_anonymous_session: Optional[str] = Header(None)):
    """
    Get or create an anonymous session for usage tracking.
    Frontend should store this and send it with subsequent requests.
    """
    service = get_model_limits_service()
    session_id = service.get_or_create_anonymous_session(x_anonymous_session)
    return {"sessionId": session_id}

@app.post("/api/generate_ai_dataset", response_model=AiDatasetResponse)
async def api_generate_ai_dataset(
    request: AiDatasetRequest,
    response: Response,
    current_user: Optional[dict] = Depends(get_current_user),
    x_anonymous_session: Optional[str] = Header(None)
):
    try:
        is_authenticated = current_user is not None
        model_id = request.model_id
        
        # Get user ID for usage tracking
        # For logged-in users: use their internal user ID
        # For anonymous users: use their anonymous session ID
        if current_user:
            user_id = current_user.get("id")
        else:
            # Get or create anonymous session for tracking
            service = get_model_limits_service()
            user_id = service.get_or_create_anonymous_session(x_anonymous_session)
            response.headers["X-Anonymous-Session"] = user_id
        
        if model_id == POWERFUL_MODEL and not is_authenticated:
            raise HTTPException(
                status_code=401, 
                detail="Login required to use the GPT-4o model. Please sign in to access this powerful model."
            )
        
        result = generate_ai_dataset(
            prompt=request.prompt, 
            type=request.type, 
            model_id=model_id,
            is_authenticated=is_authenticated,
            output_format=request.format,
            user_id=user_id  # Pass user ID or anonymous session ID for limiting
        )
        
        # Include anonymous session ID in response for frontend to store
        response_data = AiDatasetResponse(
            dataset=result['dataset'],
            metadata=result['metadata']
        )
        
        return response_data
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Error in api_generate_ai_dataset: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/sample_datasets", response_model=SampleDatasetsResponse)
async def api_get_sample_datasets(
    category: str = Query(None, description="Filter by category"),
    format: str = Query(None, description="Filter by format", alias="format")
):
    response = get_sample_datasets(category=category, format_filter=format)
    return response

@app.get("/api/sample_datasets/{dataset_id}/download")
async def api_download_sample_dataset(dataset_id: str):
    return download_sample_dataset(dataset_id)

@app.get("/api/sample_datasets/categories")
async def api_get_dataset_categories():
    return get_dataset_categories()

@app.get("/api/sample_datasets/formats")
async def api_get_dataset_formats():
    return get_dataset_formats()

@app.post("/api/analyze_dataset", response_model=DatasetAnalysisResponse)
async def api_analyze_dataset(
    file: UploadFile = File(...),
    response: Response = None,
    current_user: Optional[dict] = Depends(get_current_user),
    x_anonymous_session: Optional[str] = Header(None)
):
    try:
        if current_user:
            user_id = current_user.get("id")
        else:
            service = get_model_limits_service()
            user_id = service.get_or_create_anonymous_session(x_anonymous_session)
            if response:
                response.headers["X-Anonymous-Session"] = user_id
        
        analysis_result = await analyze_dataset_file(file, user_id)
        return analysis_result
    except Exception as e:
        print(f"Error in api_analyze_dataset: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze dataset: {str(e)}"
        )

