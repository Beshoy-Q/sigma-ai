from openai import Client
import os
from dotenv import load_dotenv
from src.prompt import *
from langchain_deepseek import ChatDeepSeek
import subprocess
import tempfile
import json
import ast

load_dotenv()
client = Client(api_key= os.getenv("OPENAI_API_KEY"))



def get_file_size_mb(file_path):
    return os.path.getsize(file_path) / (1024 * 1024)

def compress_audio(video_path, target_mb=18):
    """Extract and compress audio to stay under OpenAI's 25MB limit"""
    duration = get_video_duration(video_path)
    # Calculate target bitrate in kbps to hit target size
    target_bitrate = int((target_mb * 8 * 1024) / duration)
    target_bitrate = max(32, min(target_bitrate, 128))  # clamp between 32–128 kbps

    output_path = tempfile.mktemp(suffix=".mp3")
    subprocess.run([
        "ffmpeg", "-i", video_path,
        "-vn",                          # strip video, audio only
        "-ar", "16000",                 # 16kHz is enough for speech
        "-ac", "1",                     # mono
        "-b:a", f"{target_bitrate}k",
        output_path
    ], check=True, capture_output=True)

    return output_path

def get_video_duration(video_path):
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ], capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def transcribe_video_with_timestamps(video_path):
    print("Checking file size...")
    size_mb = get_file_size_mb(video_path)
    print(f"File size: {size_mb:.2f} MB")

    audio_to_transcribe = video_path

    if size_mb > 20:
        print(f"File too large ({size_mb:.1f}MB), compressing audio...")
        audio_to_transcribe = compress_audio(video_path)
        compressed_size = get_file_size_mb(audio_to_transcribe)
        print(f"Compressed to: {compressed_size:.2f} MB")

        # Last resort: chunk if compression wasn't enough
        if compressed_size > 24:
            print("Compression insufficient, falling back to chunking...")
            # handle chunking here if needed
            pass

    try:
        with open(audio_to_transcribe, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["segment"]
            )
    finally:
        # Cleanup temp file if we compressed
        if audio_to_transcribe != video_path and os.path.exists(audio_to_transcribe):
            os.remove(audio_to_transcribe)

    return transcript

def format_time(seconds):
    """Convert seconds to MM:SS format"""
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins:02d}:{secs:02d}"



# def transcribe_video_with_timestamps(video_path):
#     """
#     Transcribe video and get segment-level timestamps
#     """
#     print("Transcribing video...")
    
#     with open(video_path, "rb") as audio_file:
#         transcript = client.audio.transcriptions.create(
#             model="whisper-1",
#             file=audio_file,
#             response_format="verbose_json",
#             timestamp_granularities=["segment"]  
#         )
#        return transcript



def build_timestamps_dict(transcript):
    timestamps_dict = {}
    for t in transcript.segments:
        timestamps_dict[format_time(t.start)] = t.text

    return timestamps_dict



def fix_english_words(timestamps_dict):
    llm = ChatDeepSeek(
    model="deepseek-chat", 
    temperature=0)
    prompt = pull_prompt_from_langsmith("correcting-the-transcribed-text-prompt")
    corrected_dict = llm.invoke(prompt.format(timestamps_dict = timestamps_dict)).content
    return corrected_dict



def process_video(video_path):

    transcript = transcribe_video_with_timestamps(video_path)
    timestamps_dict = build_timestamps_dict(transcript)
    
    corrected = fix_english_words(timestamps_dict)
    
    try:
        corrected_json = ast.literal_eval(corrected)
    except (ValueError, SyntaxError):

        corrected_json = json.loads(corrected.replace("'", '"'))

    transformed_list = [
        {"time": timestamp, "content": text.strip()} 
        for timestamp, text in corrected_json.items()
    ]
    return transformed_list