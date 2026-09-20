import os
import requests
import re
import io

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai
from groq import Groq

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from docx import Document
except ImportError:
    Document = None

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None


app = FastAPI(
    title="SIH26154 GenAI Platform"
)


# =========================
# CORS
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# API KEYS
# =========================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")


if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is not set")

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY is not set")


# =========================
# AI CLIENTS
# =========================

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY
)

groq_client = Groq(
    api_key=GROQ_API_KEY
)


# =========================
# MODELS
# =========================

GEMINI_MODEL = "gemini-3.6-flash"
GROQ_MODEL = "openai/gpt-oss-120b"

# OpenRouter backup model
OPENROUTER_MODEL = "openai/gpt-oss-120b"


# =========================
# HEALTH CHECK
# =========================

@app.get("/")
def home():
    return {
        "status": "success",
        "message": "SIH26154 Backend is running"
    }


# =========================
# SOURCE EXTRACTION
# =========================

def extract_youtube_video_id(url: str):
    patterns = [
        r"(?:youtube\.com/watch\?v=)([A-Za-z0-9_-]{11})",
        r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None



def extract_youtube_transcript(url: str):
    if YouTubeTranscriptApi is None:
        raise HTTPException(
            status_code=500,
            detail="youtube-transcript-api is not installed."
        )

    video_id = extract_youtube_video_id(url)

    if not video_id:
        raise HTTPException(
            status_code=400,
            detail="Invalid YouTube URL."
        )

    # =====================================================
    # METHOD 1: DIRECT YOUTUBE TRANSCRIPT
    # =====================================================

    try:
        api = YouTubeTranscriptApi()

        # Get all transcripts available for the video
        transcript_list = api.list(video_id)

        transcript = None

        # Prefer manually created English
        for t in transcript_list:
            if t.language_code == "en" and not t.is_generated:
                transcript = t
                break

        # Then prefer generated English
        if transcript is None:
            for t in transcript_list:
                if t.language_code == "en":
                    transcript = t
                    break

        # Then Hindi
        if transcript is None:
            for t in transcript_list:
                if t.language_code == "hi":
                    transcript = t
                    break

        # Finally use the first available transcript
        if transcript is None:
            for t in transcript_list:
                transcript = t
                break

        if transcript is None:
            raise Exception(
                "No accessible transcript was found for this YouTube video."
            )

        fetched = transcript.fetch()

        text = " ".join(
            item.text if hasattr(item, "text") else item["text"]
            for item in fetched
        )

        if text.strip():
            print("Direct YouTube transcript succeeded.")
            return text.strip()

        raise Exception("The YouTube transcript is empty.")

    except Exception as direct_error:

        print("Direct YouTube transcript failed:")
        print(direct_error)
        print("Trying FreeTranscriptAPI fallback...")


    # =====================================================
    # METHOD 2: FREE TRANSCRIPT API FALLBACK
    # =====================================================

    try:

        response = requests.get(
            "https://api.freetranscriptapi.com/v1/transcript",
            params={
                "video_url": url
            },
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        transcript_segments = data.get("transcript", [])

        text = " ".join(
            segment.get("text", "")
            for segment in transcript_segments
            if segment.get("text")
        )

        if not text.strip():
            raise Exception(
                "FreeTranscriptAPI returned an empty transcript."
            )

        print("FreeTranscriptAPI fallback succeeded.")

        return text.strip()

    except Exception as fallback_error:

        print("FreeTranscriptAPI fallback failed:")
        print(fallback_error)

        raise HTTPException(
            status_code=422,
            detail=(
                "Could not extract a YouTube transcript. "
                "Direct YouTube extraction failed and "
                "FreeTranscriptAPI fallback also failed. "
                f"Reason: {fallback_error}"
            )
        )
        

def extract_uploaded_file(file: UploadFile, data: bytes):
    filename = (file.filename or "").lower()

    if filename.endswith(".txt"):
        return data.decode("utf-8", errors="replace")

    if filename.endswith(".pdf"):
        if PdfReader is None:
            raise RuntimeError("PDF support is not installed. Run: pip install pypdf")

        reader = PdfReader(io.BytesIO(data))
        pages = []

        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())

        result = "\n\n".join(pages).strip()

        if not result:
            raise RuntimeError(
                "No selectable text was found in this PDF. "
                "A scanned PDF may require OCR."
            )

        return result

    if filename.endswith(".docx"):
        if Document is None:
            raise RuntimeError(
                "DOCX support is not installed. Run: pip install python-docx"
            )

        document = Document(io.BytesIO(data))
        paragraphs = [
            paragraph.text.strip()
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        ]

        result = "\n".join(paragraphs).strip()

        if not result:
            raise RuntimeError("No readable text was found in the DOCX file.")

        return result

    raise ValueError("Unsupported file type. Use PDF, DOCX or TXT.")


# =========================
# REQUEST MODEL
# =========================

class ContentRequest(BaseModel):
    text: str
    outputs: list[str] = []
    audience: str = "General Public"
    tone: str = "Professional"
    language: str = "English"
    detail: str = "Medium"


# =========================
# PROMPT BUILDER
# =========================

def build_prompt(request: ContentRequest):

    output = request.outputs[0] if request.outputs else "summary"

    if output == "advisory":

        return f"""
Create ONLY the final Cybersecurity Advisory from the source.

IMPORTANT:
- Keep the output concise and proportional to the source.
- Use only facts supported by the source.
- Never invent CVEs, malware, threat actors, vulnerabilities,
  statistics, organizations, affected systems, severity levels,
  or technical details.
- Do not explain your reasoning.

Use exactly this structure:

# Cybersecurity Advisory

## 1. Overview
Write ONE concise sentence describing the main issue.

## 2. Threat / Issue
Write 1-2 short bullet points.

## 3. Affected Users or Systems
Write ONE short sentence.
If not specified:
Not specified in the source.

## 4. Risk / Impact
Write ONE short sentence describing the supported impact.

## 5. Recommended Actions
Write 1-2 short bullet points.

## 6. Key Takeaway
Write ONE concise sentence.

Target audience: {request.audience}
Tone: {request.tone}
Language: {request.language}
Detail level: {request.detail}

SOURCE:
{request.text}
"""

    elif output == "presentation":

        return f"""
Create a professional presentation outline based ONLY on the source.

IMPORTANT:
- Create 5-7 slides.
- Each slide must have a clear title.
- Use concise bullet points.
- Add 2-3 short speaker notes for each slide.
- Use only facts supported by the source.
- Do not invent facts.
- Do not explain your reasoning.
- Start directly with Slide 1.

Target audience: {request.audience}
Tone: {request.tone}
Language: {request.language}
Detail level: {request.detail}

SOURCE:
{request.text}
"""

    elif output == "infographic":

        return f"""
Create concise, infographic-ready content based ONLY on the source.

IMPORTANT:
- Create a visually structured infographic outline.
- Include:
  1. Title
  2. Key Facts
  3. Threat / Issue
  4. Risk / Impact
  5. Recommended Actions
  6. Key Takeaway
- Keep each point short.
- Use only facts supported by the source.
- Do not invent facts.
- Do not explain your reasoning.

Target audience: {request.audience}
Tone: {request.tone}
Language: {request.language}
Detail level: {request.detail}

SOURCE:
{request.text}
"""

    elif output == "linkedin":

        return f"""
Create ONLY a professional LinkedIn post based on the source.

IMPORTANT:
- Keep the post concise.
- Use only facts supported by the source.
- Do not invent facts.
- Do not explain your reasoning.
- Start directly with the LinkedIn post.
- Use short paragraphs.
- End with 3-5 relevant hashtags.

Target audience: {request.audience}
Tone: {request.tone}
Language: {request.language}
Detail level: {request.detail}

SOURCE:
{request.text}
"""

    elif output in ["x", "twitter", "thread"]:

        return f"""
Create a concise X/Twitter thread based ONLY on the source.

IMPORTANT:
- Use only facts supported by the source.
- Do not invent facts.
- Create 4-7 short posts.
- Number each post.
- Keep each post easy to read.
- Do not explain your reasoning.

Target audience: {request.audience}
Tone: {request.tone}
Language: {request.language}
Detail level: {request.detail}

SOURCE:
{request.text}
"""

    elif output == "video_package":

        return f"""
Create a professional video package based ONLY on the source.

Include:

1. Video Title
2. Hook
3. Scene-by-scene narration
4. On-screen text
5. Visual suggestions
6. Closing message

IMPORTANT:
- Use only facts supported by the source.
- Do not invent information.
- Keep the narration concise.
- Do not explain your reasoning.

Target audience: {request.audience}
Tone: {request.tone}
Language: {request.language}
Detail level: {request.detail}

SOURCE:
{request.text}
"""

    else:

        return f"""
Create ONLY a concise and accurate executive summary of the source.

IMPORTANT:
- Use only information supported by the source.
- Do not invent facts.
- Do not explain your reasoning.
- Keep the summary proportional to the source.
- Do not unnecessarily expand a short source.

Target audience: {request.audience}
Tone: {request.tone}
Language: {request.language}
Detail level: {request.detail}

SOURCE:
{request.text}
"""


# =========================
# GEMINI
# =========================

def generate_with_gemini(prompt):

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    if not response.text:
        raise RuntimeError("Gemini returned empty response")

    return response.text


# =========================
# GROQ
# =========================

def generate_with_groq(prompt):

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3
    )

    content = response.choices[0].message.content

    if not content:
        raise RuntimeError("Groq returned empty response")

    return content


# =========================
# OPENROUTER
# =========================

def generate_with_openrouter(prompt):

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": OPENROUTER_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3
        },
        timeout=30
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"OpenRouter error {response.status_code}: {response.text[:300]}"
        )

    data = response.json()

    content = data["choices"][0]["message"]["content"]

    if not content:
        raise RuntimeError("OpenRouter returned empty response")

    return content


# =========================
# THREE-PROVIDER ROUTER
# =========================

def generate_content(request: ContentRequest):

    output = request.outputs[0] if request.outputs else "summary"

    prompt = build_prompt(request)

    # ---------------------------------
    # Gemini → Groq → OpenRouter
    # ---------------------------------

    if output in ["summary", "advisory"]:

        try:
            content = generate_with_gemini(prompt)

            return {
                "content": content,
                "provider": "Gemini",
                "fallback": False
            }

        except Exception as gemini_error:

            print("Gemini failed:", gemini_error)
            print("Trying Groq fallback...")

            try:
                content = generate_with_groq(prompt)

                return {
                    "content": content,
                    "provider": "Groq",
                    "fallback": True
                }

            except Exception as groq_error:

                print("Groq failed:", groq_error)
                print("Trying OpenRouter fallback...")

                try:
                    content = generate_with_openrouter(prompt)

                    return {
                        "content": content,
                        "provider": "OpenRouter",
                        "fallback": True
                    }

                except Exception as openrouter_error:

                    print("OpenRouter failed:", openrouter_error)

                    raise HTTPException(
                        status_code=503,
                        detail="Gemini, Groq and OpenRouter failed."
                    )

    # ---------------------------------
    # Groq → Gemini → OpenRouter
    # ---------------------------------

    else:

        try:
            content = generate_with_groq(prompt)

            return {
                "content": content,
                "provider": "Groq",
                "fallback": False
            }

        except Exception as groq_error:

            print("Groq failed:", groq_error)
            print("Trying Gemini fallback...")

            try:
                content = generate_with_gemini(prompt)

                return {
                    "content": content,
                    "provider": "Gemini",
                    "fallback": True
                }

            except Exception as gemini_error:

                print("Gemini failed:", gemini_error)
                print("Trying OpenRouter fallback...")

                try:
                    content = generate_with_openrouter(prompt)

                    return {
                        "content": content,
                        "provider": "OpenRouter",
                        "fallback": True
                    }

                except Exception as openrouter_error:

                    print("OpenRouter failed:", openrouter_error)

                    raise HTTPException(
                        status_code=503,
                        detail="Groq, Gemini and OpenRouter failed."
                    )


# =========================
# YOUTUBE EXTRACTION API
# =========================

@app.post("/extract-youtube")
def extract_youtube(url: str = Form(...)):
    if not url.strip():
        raise HTTPException(status_code=400, detail="YouTube URL is required.")

    try:
        text = extract_youtube_transcript(url.strip())

        return {
            "status": "success",
            "source_type": "youtube",
            "text": text,
            "character_count": len(text)
        }

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except Exception as error:
        print("YouTube extraction failed:", error)
        raise HTTPException(status_code=422, detail=str(error))


# =========================
# FILE EXTRACTION API
# =========================

@app.post("/extract-file")
async def extract_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected.")

    allowed = (".pdf", ".docx", ".txt")

    if not file.filename.lower().endswith(allowed):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Use PDF, DOCX or TXT."
        )

    try:
        data = await file.read()

        if not data:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        text = extract_uploaded_file(file, data)

        return {
            "status": "success",
            "source_type": "file",
            "filename": file.filename,
            "text": text,
            "character_count": len(text)
        }

    except HTTPException:
        raise

    except Exception as error:
        print("File extraction failed:", error)
        raise HTTPException(status_code=422, detail=str(error))


# =========================
# TRANSFORM API
# =========================

@app.post("/transform")
def transform_content(request: ContentRequest):

    if not request.text.strip():
        raise HTTPException(
            status_code=400,
            detail="Source text cannot be empty."
        )

    result = generate_content(request)

    return {
        "status": "success",
        "generated_content": result["content"],
        "provider": result["provider"],
        "fallback_used": result["fallback"]
    }