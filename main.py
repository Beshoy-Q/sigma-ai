from pydantic import BaseModel, Field
import shutil
import tempfile
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from src.transcribe_agent.transcribe_agents import  *
from src.agents import *
from typing import Annotated
from src.utils import *
import asyncio

app = FastAPI(title= "Sigma-AI-Agents", description= "A collection of AI agents for Sigma")

class AudioRequest(BaseModel):
    """
    Request model for video transcription.
    
    Attributes:
        video_path (str): Absolute path to the video file to be transcribed
    """
    video_path: str = Field(
        ..., 
        description="Absolute path to the video file",
        example="/Users/username/videos/meeting.mp4"
    )

class TranscriptEntry(BaseModel):
    time: str
    content: str

class AudioResult(BaseModel):
    transcript: List[TranscriptEntry] = Field(..., description="List of time-stamped content")
    
class QuestionItem(BaseModel):
    question: str
    weight: int
    model_answer: str
    student_answer: str

class ReportRequest(BaseModel):
    language: str
    items: List[QuestionItem]

class EvaluationResponse(BaseModel):
    score: int | None
    reason: str | None

class ReportResponse(BaseModel):
    report: str
    explanations: List[str]


def parse_evaluation(text: str) -> dict:
    """Parses the LLM string into score and reason."""
    result = {'score': None, 'reason': None}
    score_match = re.search(r'score\s*:\s*[\'"]?(\d+)[\'"]?', text, re.IGNORECASE)
    if score_match:
        result['score'] = int(score_match.group(1))
        
    why_match = re.search(r'why\s*:\s*[\'"]?(.*?)[\'"]?\s*$', text, re.IGNORECASE | re.DOTALL)
    if why_match:
        result['reason'] = why_match.group(1)
    return result


async def evaluate_single_question_async(item: QuestionItem) -> dict:
    """Asynchronously evaluates a single question using LangSmith prompts."""
    try:
        # 1. Pull and format prompt
        prompt = pull_prompt_from_langsmith("single-question-evaluation-sigma")
        formatted_prompt = prompt(
            model_answer=item.model_answer, 
            student_answer=item.student_answer, 
            weight=item.weight, 
            question=item.question
        )
        
        # 2. Invoke LLM asynchronously
        # NOTE: Using .ainvoke() instead of .invoke() so it doesn't block the server
        response = await gpt.ainvoke(formatted_prompt)
        
        # 3. Parse and return
        return parse_evaluation(response.content)
        
    except Exception as e:
        # Always return a default structure if the LLM fails or times out
        return {"score": 0, "reason": f"Evaluation error: {str(e)}"}


async def generate_report_async(payload: ReportRequest) -> dict:
    """Evaluates all questions concurrently and generates a final report."""
    
    # 1. Evaluate all questions in PARALLEL (replaces your sequential for-loop)
    tasks = [evaluate_single_question_async(item) for item in payload.items]
    evaluations = await asyncio.gather(*tasks)
    
    # 2. Extract results
    list_of_grades = [eval['score'] for eval in evaluations]
    list_of_explanations = [eval['reason'] for eval in evaluations]
    list_of_weights = [item.weight for item in payload.items]

    # 3. Generate the final report
    try:
        prompt = pull_prompt_from_langsmith("report-generation-sigma")
        formatted_prompt = prompt(
            list_of_grades=list_of_grades, 
            list_of_weights=list_of_weights, 
            language=payload.language
        )
        response = await gpt.ainvoke(formatted_prompt)
        report_content = response.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate final report: {str(e)}")

    return dict(report=report_content, explanations=list_of_explanations)

@app.post(
    "/transcribe", 
    response_model=AudioResult, 
    summary="Transcribe videos using AI", 
    description="""Transcribe video files using OpenAI Whisper with automatic text correction.
    
    This endpoint:
    1. Extracts audio from the video file
    2. Transcribes using OpenAI Whisper with timestamp generation
    3. Corrects transcription errors using DeepSeek AI
    4. Returns formatted transcript with timestamps
    
    **Parameters:**
    - **video_path**: Absolute path to the video file (supported formats: mp4, avi, mov, etc.)
    
    **Returns:**
    - Corrected transcript with timestamps in MM:SS format
    """
)
async def transcribe(request: AudioRequest) -> AudioResult:
    """
    Transcribe a video file and return corrected transcript with timestamps.
    
    Args:
        request (AudioRequest): Request containing video file path
        
    Returns:
        AudioResult: Transcription result with corrected text
        
    Raises:
        HTTPException: If video file doesn't exist or transcription fails
    """
    try:
        if not os.path.exists(request.video_path):
            raise HTTPException(
                status_code=404, 
                detail=f"Video file not found: {request.video_path}"
            )
        
        transcript = process_video(request.video_path)
        return AudioResult(transcript=transcript)
        
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, 
            detail=f"Video file not found: {request.video_path}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Transcription failed: {str(e)}"
        )



@app.post("/evaluate-single", response_model=EvaluationResponse)
async def api_evaluate_single(item: QuestionItem):
    """API Endpoint to evaluate just one question."""
    result = await evaluate_single_question_async(item)
    return result


@app.post("/generate-report", response_model=ReportResponse)
async def api_generate_report(payload: ReportRequest):
    """API Endpoint to process an entire test/assignment and return a report."""
    result = await generate_report_async(payload)
    return result

@app.post(
    "/transcribe-test",
    response_model=AudioResult,
    summary="Transcribe an uploaded video file (test endpoint)",
    description="""Upload and transcribe a video file directly via multipart form data.
    
    This endpoint:
    1. Accepts a video file upload via multipart/form-data
    2. Saves it to a temporary location on the server
    3. Extracts audio from the video file
    4. Transcribes using OpenAI Whisper with timestamp generation
    5. Corrects transcription errors using DeepSeek AI
    6. Returns formatted transcript with timestamps
    7. Cleans up the temporary file after processing
    
    **Parameters:**
    - **file**: The video file to upload (supported formats: mp4, avi, mov, etc.)
    
    **Returns:**
    - Corrected transcript with timestamps in MM:SS format
    """
)
async def transcribe_test(
    file: UploadFile = File(..., description="Video file to transcribe (mp4, avi, mov, etc.)")
) -> AudioResult:
    """
    Accept an uploaded video file, transcribe it, and return the corrected transcript.

    Args:
        file (UploadFile): The uploaded video file.

    Returns:
        AudioResult: Transcription result with corrected text.

    Raises:
        HTTPException: If the file is invalid or transcription fails.
    """
    # Preserve the original file extension so ffmpeg/whisper can detect the format
    suffix = os.path.splitext(file.filename)[-1] if file.filename else ".mp4"

    tmp_path = None
    try:
        # Write the uploaded bytes to a named temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        transcript = process_video(tmp_path)
        return AudioResult(transcript=transcript)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {str(e)}"
        )
    finally:
        # Always clean up the temp file, even if an error occurred
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

@app.post("/flashcards_construct", description= """
Construct flashcards based on the provided content and number of cards.

    **Parameters:**
    - **content**: The content to be used for constructing flashcards.
    - **number_of_cards**: The number of flashcards to construct.

    **Returns:**
    - {"response": response} where response is the constructed flashcards.
""")
async def flash_cards_construction_endpoint(content: Annotated[UploadFile, File()], number_of_cards: int):
    formatted_content = await read_document(content)
    response = construct_flash_cards(content= formatted_content, number_of_cards= number_of_cards)
    return {"response": response}