import os
import io
import re
import requests
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from fastapi import (
    FastAPI,
    HTTPException,
    UploadFile,
    File,
    Form,
)

from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

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

from pptx import Presentation

import fitz
import pytesseract
from PIL import Image
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="SIH26154 GenAI Platform"
)
app.mount(
    "/generated-infographics",
    StaticFiles(directory="generated_infographics"),
    name="generated-infographics"
)

# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# API KEYS
# =========================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

SLIDEFORGE_API_KEY = os.getenv("SLIDEFORGE_API_KEY")
SLIDEFORGE_API_BASE = "https://api.slideforge.dev"
SLIDEFORGE_THEME_ID = os.getenv(
    "SLIDEFORGE_THEME_ID",
    "slideforge_standard"
)

BANNERBEAR_API_KEY = os.getenv("BANNERBEAR_API_KEY")
BANNERBEAR_TEMPLATE_UID = os.getenv("BANNERBEAR_TEMPLATE_UID")
BANNERBEAR_API_BASE = "https://sync.api.bannerbear.com/v5"


if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is not set")

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY is not set")


# =========================================================
# AI CLIENTS
# =========================================================

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY
)

groq_client = Groq(
    api_key=GROQ_API_KEY
)


# =========================================================
# MODELS
# =========================================================

GEMINI_MODEL = "gemini-3.6-flash"

GROQ_MODEL = "openai/gpt-oss-120b"

OPENROUTER_MODEL = "openai/gpt-oss-120b"


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/")
def home():
    return {
        "status": "success",
        "message": "SIH26154 Backend is running"
    }


# =========================================================
# YOUTUBE EXTRACTION
# =========================================================

def extract_youtube_video_id(url: str):

    patterns = [
        r"(?:youtube\.com/watch\?v=)([A-Za-z0-9_-]{11})",
        r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/shorts/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/embed/)([A-Za-z0-9_-]{11})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            url
        )

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

        transcript_list = api.list(
            video_id
        )

        transcript = None

        # Prefer manually created English
        for item in transcript_list:

            if (
                item.language_code == "en"
                and not item.is_generated
            ):
                transcript = item
                break

        # Generated English
        if transcript is None:

            for item in transcript_list:

                if item.language_code == "en":
                    transcript = item
                    break

        # Hindi
        if transcript is None:

            for item in transcript_list:

                if item.language_code == "hi":
                    transcript = item
                    break

        # First available transcript
        if transcript is None:

            for item in transcript_list:
                transcript = item
                break

        if transcript is None:
            raise Exception(
                "No accessible transcript was found."
            )

        fetched = transcript.fetch()

        text = " ".join(
            item.text
            if hasattr(item, "text")
            else item["text"]
            for item in fetched
        )

        if text.strip():

            print(
                "Direct YouTube transcript succeeded."
            )

            return text.strip()

        raise Exception(
            "The YouTube transcript is empty."
        )

    except Exception as direct_error:

        print(
            "Direct YouTube transcript failed:"
        )

        print(direct_error)

        print(
            "Trying FreeTranscriptAPI fallback..."
        )

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

        transcript_segments = data.get(
            "transcript",
            []
        )

        text = " ".join(
            segment.get("text", "")
            for segment in transcript_segments
            if segment.get("text")
        )

        if not text.strip():
            raise Exception(
                "FreeTranscriptAPI returned an empty transcript."
            )

        print(
            "FreeTranscriptAPI fallback succeeded."
        )

        return text.strip()

    except Exception as fallback_error:

        print(
            "FreeTranscriptAPI fallback failed:"
        )

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


# =========================================================
# FILE EXTRACTION
# =========================================================

def extract_uploaded_file(
    file: UploadFile,
    data: bytes
):

    filename = (
        file.filename or ""
    ).lower()

    # =====================================================
    # TXT
    # =====================================================

    if filename.endswith(".txt"):

        return data.decode(
            "utf-8",
            errors="replace"
        )

    # =====================================================
    # PDF
    # =====================================================

    if filename.endswith(".pdf"):

        if PdfReader is None:
            raise RuntimeError(
                "PDF support is not installed. "
                "Run: pip install pypdf"
            )

        reader = PdfReader(
            io.BytesIO(data)
        )

        pages = []

        for page in reader.pages:

            text = page.extract_text() or ""

            if text.strip():
                pages.append(
                    text.strip()
                )

        result = "\n\n".join(
            pages
        ).strip()

        if result:
            return result

        # Scanned PDF fallback: render each page and OCR it.
        ocr_pages = []
        pdf = fitz.open(stream=data, filetype="pdf")

        try:
            for page in pdf:
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    alpha=False
                )
                image = Image.open(
                    io.BytesIO(pix.tobytes("png"))
                )
                text = pytesseract.image_to_string(
                    image,
                    lang="eng"
                ).strip()
                if text:
                    ocr_pages.append(text)
        finally:
            pdf.close()

        ocr_result = "\n\n".join(ocr_pages).strip()

        if not ocr_result:
            raise RuntimeError(
                "OCR could not detect readable text in this PDF."
            )

        return ocr_result

    # =====================================================
    # DOCX
    # =====================================================

    if filename.endswith(".docx"):

        if Document is None:
            raise RuntimeError(
                "DOCX support is not installed. "
                "Run: pip install python-docx"
            )

        document = Document(
            io.BytesIO(data)
        )

        paragraphs = [
            paragraph.text.strip()
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        ]

        result = "\n".join(
            paragraphs
        ).strip()

        if not result:

            raise RuntimeError(
                "No readable text was found in the DOCX file."
            )

        return result

    raise ValueError(
        "Unsupported file type. Use PDF, DOCX or TXT."
    )

# =========================================================
# WEB / ARTICLE EXTRACTION
# =========================================================

def extract_web_article(url: str):
    """
    Extract readable text from a public webpage/article.
    Uses the webpage HTML and removes common non-content elements.
    """

    if not url or not url.strip():
        raise ValueError("Web/article URL is required.")

    url = url.strip()

    if not (
        url.startswith("http://")
        or url.startswith("https://")
    ):
        raise ValueError(
            "Please enter a valid HTTP or HTTPS URL."
        )

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/131.0 Safari/537.36"
                )
            },
            timeout=30
        )

        response.raise_for_status()

    except Exception as error:
        raise RuntimeError(
            f"Unable to access webpage: {error}"
        )

    html = response.text

    # Remove scripts, styles and non-content elements.
    html = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL
    )

    html = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL
    )

    html = re.sub(
        r"<noscript\b[^>]*>.*?</noscript>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL
    )

    html = re.sub(
        r"<nav\b[^>]*>.*?</nav>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL
    )

    html = re.sub(
        r"<footer\b[^>]*>.*?</footer>",
        " ",
        html,
        flags=re.IGNORECASE | re.DOTALL
    )

    # Convert common block tags to line breaks.
    html = re.sub(
        r"</(p|div|article|section|h1|h2|h3|h4|li|br)>",
        "\n",
        html,
        flags=re.IGNORECASE
    )

    # Remove remaining HTML tags.
    text = re.sub(
        r"<[^>]+>",
        " ",
        html
    )

    # Decode basic HTML entities.
    text = (
        text.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
    )

    # Normalize whitespace.
    lines = []

    for line in text.splitlines():
        line = re.sub(
            r"\s+",
            " ",
            line
        ).strip()

        if line:
            lines.append(line)

    result = "\n".join(lines).strip()

    if len(result) < 100:
        raise RuntimeError(
            "The webpage did not contain enough readable text."
        )

    return result


# =========================================================
# IMAGE EXTRACTION
# =========================================================

def extract_image_content(
    filename: str,
    data: bytes
):
    """
    Extract useful source information from an image
    using Gemini multimodal understanding.
    """

    if not data:
        raise ValueError(
            "The uploaded image is empty."
        )

    suffix = Path(
        filename or "image.jpg"
    ).suffix.lower()

    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }

    mime_type = mime_types.get(
        suffix,
        "image/jpeg"
    )

    prompt = """
Analyze this image as source material for the
SIH26154 GenAI content transformation platform.

Extract all useful readable and contextual information
from the image.

Rules:

- Read visible text accurately.
- Preserve important numbers, names and dates.
- Describe important visual information when it is
  necessary to understand the source.
- Do not invent missing information.
- If something cannot be read, say so.
- Return clean source text that can be passed into
  the normal content transformation pipeline.
- Do not provide chain-of-thought.
"""

    try:

        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": prompt
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": data
                            }
                        }
                    ]
                }
            ]
        )

        if not response.text:
            raise RuntimeError(
                "Gemini returned no readable image content."
            )

        return response.text.strip()

    except Exception as error:

        raise RuntimeError(
            f"Image understanding failed: {error}"
        )


# =========================================================
# VIDEO EXTRACTION
# =========================================================

def extract_video_audio_text(
    filename: str,
    data: bytes
):
    """
    Extract speech from an uploaded video using FFmpeg
    + Groq Whisper.

    Requires FFmpeg to be installed and available
    in the system PATH.
    """

    if not data:
        raise ValueError(
            "The uploaded video is empty."
        )

    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not configured."
        )

    suffix = (
        Path(filename or "video.mp4").suffix
        or ".mp4"
    )

    video_path = None
    audio_path = None

    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix
        ) as video_file:

            video_file.write(data)
            video_path = video_file.name

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".mp3"
        ) as audio_file:

            audio_path = audio_file.name

        # Extract audio from video.
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-vn",
                "-acodec",
                "libmp3lame",
                "-ar",
                "16000",
                "-ac",
                "1",
                audio_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        with open(
            audio_path,
            "rb"
        ) as audio:

            transcription = groq_client.audio.transcriptions.create(
                file=(
                    "video_audio.mp3",
                    audio.read()
                ),
                model="whisper-large-v3-turbo",
                response_format="text",
            )

        if not transcription:
            raise RuntimeError(
                "Video transcription returned empty text."
            )

        return str(
            transcription
        ).strip()

    except FileNotFoundError:

        raise RuntimeError(
            "FFmpeg is not installed or is not available "
            "in PATH. Install FFmpeg and restart the backend."
        )

    except subprocess.CalledProcessError as error:

        raise RuntimeError(
            "Unable to extract audio from the video. "
            f"FFmpeg error: {error.stderr}"
        )

    except Exception as error:

        raise RuntimeError(
            f"Video transcription failed: {error}"
        )

    finally:

        for path in [
            video_path,
            audio_path
        ]:

            if path:

                try:
                    os.remove(path)
                except OSError:
                    pass
# =========================================================
# REQUEST MODELS
# =========================================================

class ContentRequest(BaseModel):

    text: str

    outputs: list[str] = Field(
        default_factory=list
    )

    audience: str = "General Public"

    tone: str = "Professional"

    language: str = "English"

    detail: str = "Medium"

    objective: str = "Inform"

    content_style: str = "Standard"


class PresentationExportRequest(BaseModel):

    content: str


# =========================================================
# PROMPT BUILDER
# =========================================================

def build_prompt(
    request: ContentRequest
):

    output = (
        request.outputs[0].strip().lower()
        if request.outputs
        else "summary"
    )

    output_mapping = {

        "executive summary": "summary",

        "summary": "summary",

        "advisory": "advisory",

        "linkedin post": "linkedin",

        "linkedin": "linkedin",

        "twitter / x": "twitter",

        "twitter/x": "twitter",

        "twitter": "twitter",

        "x": "twitter",

        "thread": "twitter",

        "infographic": "infographic",

        "presentation": "presentation",

        "video package": "video_package",

        "video_package": "video_package",
    }

    output = output_mapping.get(
        output,
        output
    )

    common = f"""
You are an AI content-transformation specialist for SIH26154
"GenAI Platform for Automated Content Transformation".

Transform ONE common source into the requested professional deliverable.

SOURCE-GROUNDING RULES:

- Treat the supplied source as the primary factual authority.
- Use only information supported by the source.
- Never invent facts, statistics, dates, names, organizations,
  quotations, products, vulnerabilities, CVEs, threat actors,
  outcomes, technical specifications, or other unsupported details.
- If an important detail is absent, write
  "Not specified in the source." where appropriate,
  or omit it.
- Preserve the source's meaning and important context.
- Do not exaggerate or sensationalize.
- Do not reveal chain-of-thought.
- Return only the requested deliverable.

OPERATOR CONTROLS:

Target audience: {request.audience}
Tone: {request.tone}
Language: {request.language}
Level of detail: {request.detail}
Communication objective: {request.objective}
Content style: {request.content_style}

Apply ALL operator controls to the final deliverable.

The selected language applies to the complete deliverable.

Detail controls depth, never factual invention.
"""

    # =====================================================
    # EXECUTIVE SUMMARY
    # =====================================================

    if output == "summary":

        return f"""
{common}

Create ONLY a professional Executive Summary.

Requirements:

- Be concise and proportional to the source.
- State the subject and central message clearly.
- Include the most important supported facts,
  findings and implications.
- Include recommendations or next steps only when supported.
- Adapt to the selected audience and objective.
- Use short paragraphs and/or concise bullets where useful.
- Do not unnecessarily expand a short source.
- Start directly with the executive summary.

SOURCE:

{request.text}
"""

    # =====================================================
    # ADVISORY
    # =====================================================

    if output == "advisory":

        return f"""
{common}

Create a professional Advisory based ONLY on the source.

IMPORTANT:

This is DOMAIN-NEUTRAL.

Do not automatically turn every source into a
cybersecurity advisory.

Preserve the source's actual domain, including:

- technology
- cybersecurity
- business
- education
- healthcare
- operations
- research
- public information
- or any other subject

Use exactly:

# Advisory

## 1. Overview

One concise paragraph describing the main issue,
development or subject.

## 2. Key Issue / Findings

2-5 concise source-supported bullet points.

## 3. Affected Audience / Systems

State who or what is affected when specified.

Otherwise:

Not specified in the source.

## 4. Risk / Impact

Describe supported risks, consequences,
importance or impact.

Do not assign an unsupported severity level.

## 5. Recommended Actions

Give practical actions supported or directly
derived from the source.

Do not invent technical requirements,
policies or procedures.

## 6. Key Takeaway

One concise factual closing statement.

SOURCE:

{request.text}
"""

    # =====================================================
    # LINKEDIN
    # =====================================================

    if output == "linkedin":

        return f"""
{common}

Create ONLY a polished professional LinkedIn post.

Requirements:

- Start with an engaging but factual opening.
- Use short readable paragraphs.
- Communicate the most relevant source-supported insight.
- Match audience, tone, objective and content style.
- Do not invent claims or statistics.
- End with 3-5 relevant hashtags.
- Do not add a heading such as "LinkedIn Post".

SOURCE:

{request.text}
"""

    # =====================================================
    # TWITTER / X
    # =====================================================

    if output == "twitter":

        return f"""
{common}

Create a concise X/Twitter thread based ONLY on the source.

Requirements:

- Create 4-7 numbered posts when the source supports a thread.
- Each post communicates one clear idea.
- Keep posts concise and easy to scan.
- Preserve factual accuracy and source context.
- Make the sequence logically progressive.
- Match the operator's language and tone.
- End with the key takeaway.
- Do not explain your reasoning.

SOURCE:

{request.text}
"""

    # =====================================================
    # INFOGRAPHIC
    # =====================================================

    if output == "infographic":

        return f"""
{common}

Create production-ready infographic content
based ONLY on the source.

Use exactly:

# Infographic Content

## 1. Title

Short, clear and factual headline.

## 2. Key Message

One sentence expressing the central message.

## 3. Key Facts

3-6 short source-supported facts or points.

## 4. Main Issue / Topic

Concise explanation of the central subject.

## 5. Impact / Significance

Short source-supported points explaining why it matters.

## 6. Recommended Actions

Short actionable points supported by the source.

## 7. Key Takeaway

One concise factual closing message.

## 8. Layout Recommendation

Describe a practical visual hierarchy including:

- Header/title area
- Main or central message
- Key-fact blocks
- Impact/risk section where relevant
- Recommended-actions section
- Footer/key takeaway

## 9. Visual Recommendations

Suggest suitable icons, diagrams, imagery,
charts, timelines or visual metaphors.

Never invent numbers or data for charts.

Keep wording short enough for an actual infographic.

SOURCE:

{request.text}
"""

    # =====================================================
    # PRESENTATION
    # =====================================================

    if output == "presentation":

        return f"""
{common}

Create a professional presentation outline
based ONLY on the source.

Create 5-7 slides when the source supports them.

If the source is too short, use fewer slides
rather than inventing content.

Every slide MUST contain:

- Slide number
- Clear slide title
- 2-5 concise content bullets
- 2-3 short speaker notes

Use this logical flow when supported:

Slide 1: Title / Core Message
Slide 2: Context / Background
Slide 3: Key Information / Findings
Slide 4: Analysis / Impact
Slide 5: Recommendations / Actions
Slide 6: Practical Implications / Next Steps
Slide 7: Key Takeaway

Rules:

- Use only source-supported information.
- Do not fabricate statistics or examples.
- Make the slides presentation-ready.
- Speaker notes should add useful context
  rather than repeat every bullet.
- Start directly with Slide 1.

SOURCE:

{request.text}
"""

    # =====================================================
    # VIDEO PACKAGE
    # =====================================================

    if output == "video_package":

        return f"""
{common}

Create a COMPLETE professional Video Package
based ONLY on the source.

This must be usable as a real production blueprint,
not merely a summary.

Use exactly:

# Video Package

## 1. Video Title

Concise factual title.

## 2. Hook

Short engaging opening without sensationalism
or unsupported claims.

## 3. Full Video Script

Complete script from opening through closing.

## 4. Storyboard

For every scene include:

- Scene number
- Scene purpose
- Narration
- On-screen text
- Visual recommendation

## 5. Scene Descriptions

Describe what should visually appear in each scene
and how it supports the message.

## 6. Narration Text

Clean narration suitable for voice recording.

Do not put production directions inside the narration.

## 7. Subtitles

Subtitle-ready text broken into short readable segments.

## 8. Visual Recommendations

Recommend footage, images, icons, diagrams,
charts or animations.

Never invent chart data.

## 9. Closing Message

Concise factual closing aligned with
the communication objective.

Additional rules:

- Keep depth proportional to the selected detail level and source.
- Maintain consistent facts and terminology across all sections.
- Do not add unsupported scenes, claims or examples.
- Do not generate audio or TTS.
- This output is the content and production package only.

SOURCE:

{request.text}
"""

    # =====================================================
    # SAFE FALLBACK
    # =====================================================

    return f"""
{common}

Create a concise professional transformation of the source.

Preserve the source's meaning and follow all operator controls.

SOURCE:

{request.text}
"""


# =========================================================
# GEMINI
# =========================================================

def generate_with_gemini(
    prompt: str
):

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )

    if not response.text:

        raise RuntimeError(
            "Gemini returned empty response"
        )

    return response.text


# =========================================================
# GROQ
# =========================================================

def generate_with_groq(
    prompt: str
):

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

        raise RuntimeError(
            "Groq returned empty response"
        )

    return content


# =========================================================
# OPENROUTER
# =========================================================

def generate_with_openrouter(
    prompt: str
):

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": (
                f"Bearer {OPENROUTER_API_KEY}"
            ),
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
            f"OpenRouter error "
            f"{response.status_code}: "
            f"{response.text[:300]}"
        )

    data = response.json()

    content = (
        data["choices"][0]["message"]["content"]
    )

    if not content:

        raise RuntimeError(
            "OpenRouter returned empty response"
        )

    return content


# =========================================================
# SLIDEFORGE PRESENTATION SPECIALIST
# =========================================================

def split_presentation_sections(
    content: str
):

    text = content.strip()

    if not text:

        raise RuntimeError(
            "Presentation content is empty."
        )

    sections = re.split(
        r"(?=^#{1,3}\s*Slide\s+\d+\s*:?)",
        text,
        flags=(
            re.IGNORECASE |
            re.MULTILINE
        )
    )

    sections = [
        section.strip()
        for section in sections
        if section.strip()
    ]

    if len(sections) <= 1:

        sections = [
            section.strip()
            for section in re.split(
                r"\n\s*\n",
                text
            )
            if section.strip()
        ]

    return (
        sections or [text]
    )[:10]


def generate_presentation_with_slideforge(
    content: str,
    request: ContentRequest
):

    if not SLIDEFORGE_API_KEY:

        raise RuntimeError(
            "SLIDEFORGE_API_KEY is not configured."
        )

    sections = split_presentation_sections(
        content
    )

    slides = []

    for index, section in enumerate(
        sections,
        start=1
    ):

        slides.append(
            {
                "brief": (
                    f"Create slide {index} "
                    "of a professional presentation. "
                    f"Audience: {request.audience}. "
                    f"Tone: {request.tone}. "
                    f"Language: {request.language}. "
                    f"Detail: {request.detail}. "
                    f"Objective: {request.objective}. "
                    f"Style: {request.content_style}. "
                    "Use only the supplied presentation "
                    "content; do not invent facts. "
                    f"Slide content:\n{section}"
                )
            }
        )

    response = requests.post(
        (
            f"{SLIDEFORGE_API_BASE}"
            "/v1/render/intent/deck"
        ),
        headers={
            "Authorization": (
                f"Bearer {SLIDEFORGE_API_KEY}"
            ),
            "Content-Type": "application/json",
        },
        json={
            "name": (
                "SIH26154 Generated Presentation"
            ),
            "theme_id": SLIDEFORGE_THEME_ID,
            "slides": slides,
        },
        timeout=90,
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"SlideForge error "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()

    if data.get("status") != "complete":

        raise RuntimeError(
            "SlideForge did not complete "
            f"the deck: {data}"
        )

    job_id = data.get("job_id")

    if not job_id:

        raise RuntimeError(
            "SlideForge did not return "
            "a deck job ID."
        )

    return job_id, data


def download_slideforge_pptx(
    job_id: str
):

    if not SLIDEFORGE_API_KEY:

        raise RuntimeError(
            "SLIDEFORGE_API_KEY is not configured."
        )

    response = requests.get(
        (
            f"{SLIDEFORGE_API_BASE}"
            f"/v1/jobs/{job_id}/pptx"
        ),
        headers={
            "Authorization": (
                f"Bearer {SLIDEFORGE_API_KEY}"
            )
        },
        timeout=90,
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"SlideForge PPTX download error "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        )

    if not response.content:

        raise RuntimeError(
            "SlideForge returned an empty PPTX file."
        )

    output = io.BytesIO(
        response.content
    )

    output.seek(0)

    return output


# =========================================================
# BANNERBEAR INFOGRAPHIC TEST
# =========================================================

def generate_bannerbear_infographic_test():

    if not BANNERBEAR_API_KEY:

        raise RuntimeError(
            "BANNERBEAR_API_KEY is not configured."
        )

    if not BANNERBEAR_TEMPLATE_UID:

        raise RuntimeError(
            "BANNERBEAR_TEMPLATE_UID is not configured."
        )

    modifications = {
        "objects": [

            {
                "name": "title",
                "text": (
                    "AI-Powered Content Transformation"
                )
            },

            {
                "name": "subtitle",
                "text": (
                    "SIH26154 • Automated Content Creation"
                )
            },

            {
                "name": "section_1_heading",
                "text": "What It Does"
            },

            {
                "name": "section_1_content",
                "text": (
                    "Transforms one source into "
                    "multiple audience-ready content formats."
                )
            },

            {
                "name": "section_2_heading",
                "text": "Key Benefits"
            },

            {
                "name": "section_2_content",
                "text": (
                    "Improves consistency, reduces manual "
                    "effort and accelerates content creation."
                )
            },

            {
                "name": "section_3_heading",
                "text": "Multiple Deliverables"
            },

            {
                "name": "section_3_content",
                "text": (
                    "Generate summaries, advisories, "
                    "social posts, presentations "
                    "and video packages."
                )
            },

            {
                "name": "takeaway_heading",
                "text": "Key Takeaway"
            },

            {
                "name": "takeaway_content",
                "text": (
                    "One source can become "
                    "multiple professional deliverables."
                )
            },

            {
                "name": "footer",
                "text": "SIH26154 • Team NEX GEN"
            }
        ]
    }

    response = requests.post(
        f"{BANNERBEAR_API_BASE}/images",
        headers={
            "Authorization": (
                f"Bearer {BANNERBEAR_API_KEY}"
            ),
            "Content-Type": "application/json",
        },
        json={
            "template": BANNERBEAR_TEMPLATE_UID,
            "formats": ["png"],
            "modifications": modifications,
        },
        timeout=60,
    )

    if response.status_code not in (
        200,
        201
    ):

        raise RuntimeError(
            f"Bannerbear error "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()

    print(
        "Bannerbear response:",
        data
    )

    return data


# =========================================================
# BANNERBEAR PRODUCTION INFOGRAPHIC
# =========================================================

def generate_bannerbear_infographic(
    content: str
):

    if not BANNERBEAR_API_KEY:

        raise RuntimeError(
            "BANNERBEAR_API_KEY is not configured."
        )

    if not BANNERBEAR_TEMPLATE_UID:

        raise RuntimeError(
            "BANNERBEAR_TEMPLATE_UID is not configured."
        )

    modifications = {
        "objects": [

            {
                "name": "title",
                "text": content[:100]
            },

            {
                "name": "subtitle",
                "text": "AI-Generated Infographic"
            }
        ]
    }

    response = requests.post(
        f"{BANNERBEAR_API_BASE}/images",
        headers={
            "Authorization": (
                f"Bearer {BANNERBEAR_API_KEY}"
            ),
            "Content-Type": "application/json",
        },
        json={
            "template": BANNERBEAR_TEMPLATE_UID,
            "formats": ["png"],
            "modifications": modifications,
        },
        timeout=60,
    )

    if response.status_code not in (
        200,
        201
    ):

        raise RuntimeError(
            f"Bannerbear error "
            f"{response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()

    if not data.get(
        "files",
        {}
    ).get("png"):

        raise RuntimeError(
            f"Bannerbear did not return "
            f"a PNG file: {data}"
        )

    return data
def generate_html_infographic(content: str):
    output_dir = (
        Path(__file__).resolve().parent
        / "generated_infographics"
    )

    output_dir.mkdir(exist_ok=True)

    def extract(pattern, fallback=""):
        match = re.search(
            pattern,
            content,
            flags=re.IGNORECASE | re.DOTALL
        )

        return (
            match.group(1).strip()
            if match
            else fallback
        )

    title = extract(
        r"##\s*1\.\s*Title\s*(.*?)(?=##\s*2\.)",
        "AI Content Transformation"
    )

    key_message = extract(
        r"##\s*2\.\s*Key Message\s*(.*?)(?=##\s*3\.)",
        ""
    )

    key_facts = extract(
        r"##\s*3\.\s*Key Facts\s*(.*?)(?=##\s*4\.)",
        ""
    )

    main_topic = extract(
        r"##\s*4\.\s*Main Issue\s*/\s*Topic\s*(.*?)(?=##\s*5\.)",
        ""
    )

    impact = extract(
        r"##\s*5\.\s*Impact\s*/\s*Significance\s*(.*?)(?=##\s*6\.)",
        ""
    )

    actions = extract(
        r"##\s*6\.\s*Recommended Actions\s*(.*?)(?=##\s*7\.)",
        ""
    )

    takeaway = extract(
        r"##\s*7\.\s*Key Takeaway\s*(.*?)(?=##\s*8\.)",
        ""
    )

    def clean(value):
        value = re.sub(
            r"\*\*(.*?)\*\*",
            r"\1",
            value
        )

        value = re.sub(
            r"^[-*•]\s*",
            "",
            value.strip()
        )

        value = re.sub(
            r"\n+",
            " ",
            value
        )

        return value.strip()

    title = clean(title)
    key_message = clean(key_message)
    main_topic = clean(main_topic)
    takeaway = clean(takeaway)

    facts = [
        clean(x)
        for x in re.findall(
            r"[-*•]\s+(.+)",
            key_facts
        )
    ][:3]

    impact_points = [
        clean(x)
        for x in re.findall(
            r"[-*•]\s+(.+)",
            impact
        )
    ][:3]

    action_points = [
        clean(x)
        for x in re.findall(
            r"[-*•]\s+(.+)",
            actions
        )
    ][:3]

    while len(facts) < 3:
        facts.append(
            "Key insight from the supplied source."
        )

    while len(impact_points) < 2:
        impact_points.append(
            "Relevant impact identified from the source."
        )

    while len(action_points) < 3:
        action_points.append(
            "Recommended action based on the source."
        )

    def esc(value):
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">

<style>

* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    width: 1200px;
    height: 1600px;
    font-family: Arial, Helvetica, sans-serif;
    background: #f8fafc;
    color: #0f172a;
}}

.page {{
    width: 1200px;
    min-height: 1600px;
    padding: 70px;
}}

.title {{
    font-size: 58px;
    font-weight: 800;
    line-height: 1.08;
    margin-bottom: 18px;
}}

.subtitle {{
    font-size: 27px;
    color: #2563eb;
    line-height: 1.35;
    margin-bottom: 45px;
}}

.hero {{
    background: linear-gradient(
        135deg,
        #2563eb,
        #7c3aed
    );

    color: white;
    border-radius: 32px;
    padding: 42px;
    margin-bottom: 42px;
}}

.hero-label {{
    font-size: 20px;
    font-weight: 700;
    text-transform: uppercase;
    opacity: 0.85;
    letter-spacing: 2px;
}}

.hero-text {{
    font-size: 34px;
    font-weight: 700;
    line-height: 1.25;
    margin-top: 16px;
}}

.section-title {{
    font-size: 28px;
    font-weight: 800;
    margin: 30px 0 18px;
}}

.cards {{
    display: flex;
    gap: 18px;
}}

.card {{
    flex: 1;
    min-height: 190px;
    background: white;
    border-radius: 24px;
    padding: 25px;
    border: 1px solid #e2e8f0;
}}

.number {{
    font-size: 22px;
    font-weight: 800;
    color: #2563eb;
}}

.card-text {{
    font-size: 21px;
    line-height: 1.35;
    margin-top: 14px;
}}

.topic {{
    background: #eef2ff;
    border-left: 8px solid #7c3aed;
    border-radius: 20px;
    padding: 28px;
    font-size: 23px;
    line-height: 1.4;
}}

.impact {{
    display: flex;
    gap: 18px;
}}

.impact-card {{
    flex: 1;
    background: #ecfdf5;
    border-radius: 22px;
    padding: 25px;
    font-size: 20px;
    line-height: 1.4;
}}

.actions {{
    display: flex;
    flex-direction: column;
    gap: 14px;
}}

.action {{
    display: flex;
    gap: 18px;
    align-items: center;
    background: white;
    border-radius: 18px;
    padding: 20px 24px;
    border: 1px solid #e2e8f0;
}}

.action-number {{
    width: 42px;
    height: 42px;
    border-radius: 50%;
    background: #ea580c;
    color: white;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
    flex-shrink: 0;
}}

.action-text {{
    font-size: 20px;
    line-height: 1.3;
}}

.takeaway {{
    margin-top: 38px;
    background: #0f172a;
    color: white;
    border-radius: 26px;
    padding: 32px;
}}

.takeaway-title {{
    color: #38bdf8;
    font-size: 20px;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 2px;
}}

.takeaway-text {{
    margin-top: 12px;
    font-size: 27px;
    line-height: 1.3;
    font-weight: 700;
}}

.footer {{
    margin-top: 28px;
    text-align: center;
    color: #64748b;
    font-size: 16px;
}}

</style>
</head>

<body>

<div class="page">

    <div class="title">
        {esc(title)}
    </div>

    <div class="subtitle">
        {esc(key_message)}
    </div>

    <div class="hero">

        <div class="hero-label">
            Main Topic
        </div>

        <div class="hero-text">
            {esc(main_topic)}
        </div>

    </div>

    <div class="section-title">
        Key Insights
    </div>

    <div class="cards">

        <div class="card">

            <div class="number">
                01
            </div>

            <div class="card-text">
                {esc(facts[0])}
            </div>

        </div>

        <div class="card">

            <div class="number">
                02
            </div>

            <div class="card-text">
                {esc(facts[1])}
            </div>

        </div>

        <div class="card">

            <div class="number">
                03
            </div>

            <div class="card-text">
                {esc(facts[2])}
            </div>

        </div>

    </div>

    <div class="section-title">
        Impact &amp; Significance
    </div>

    <div class="impact">

        <div class="impact-card">
            {esc(impact_points[0])}
        </div>

        <div class="impact-card">
            {esc(impact_points[1])}
        </div>

    </div>

    <div class="section-title">
        Recommended Actions
    </div>

    <div class="actions">

        <div class="action">

            <div class="action-number">
                1
            </div>

            <div class="action-text">
                {esc(action_points[0])}
            </div>

        </div>

        <div class="action">

            <div class="action-number">
                2
            </div>

            <div class="action-text">
                {esc(action_points[1])}
            </div>

        </div>

        <div class="action">

            <div class="action-number">
                3
            </div>

            <div class="action-text">
                {esc(action_points[2])}
            </div>

        </div>

    </div>

    <div class="takeaway">

        <div class="takeaway-title">
            Key Takeaway
        </div>

        <div class="takeaway-text">
            {esc(takeaway)}
        </div>

    </div>

    <div class="footer">
        SIH26154 • Team NEX GEN
    </div>

</div>

</body>
</html>
"""

    html_file = output_dir / "infographic.html"
    png_file = output_dir / "infographic.png"

    html_file.write_text(
        html,
        encoding="utf-8"
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            viewport={
                "width": 1200,
                "height": 1600
            },
            device_scale_factor=1
        )

        page.goto(
            html_file.as_uri(),
            wait_until="networkidle"
        )

        page.screenshot(
            path=str(png_file),
            full_page=True
        )

        browser.close()

    return str(png_file)

    def extract_section(start_pattern, end_pattern=None):
        if end_pattern:
            pattern = rf"{start_pattern}\s*(.*?)(?={end_pattern})"
        else:
            pattern = rf"{start_pattern}\s*(.*)$"

        match = re.search(
            pattern,
            content,
            flags=re.IGNORECASE | re.DOTALL
        )

        if not match:
            return ""

        return match.group(1).strip()

    def clean_text(value, max_length):
        value = value.strip()

        value = re.sub(r"^#+\s*", "", value)
        value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
        value = re.sub(r"\n\s*[-*•]\s*", " • ", value)
        value = re.sub(r"\n+", " ", value)
        value = re.sub(r"\s+", " ", value)

        return value[:max_length].strip()

    title = extract_section(
        r"##\s*1\.\s*Title",
        r"##\s*2\.\s*Key Message"
    )

    key_message = extract_section(
        r"##\s*2\.\s*Key Message",
        r"##\s*3\.\s*Key Facts"
    )

    key_facts = extract_section(
        r"##\s*3\.\s*Key Facts",
        r"##\s*4\.\s*Main Issue\s*/\s*Topic"
    )

    main_issue = extract_section(
        r"##\s*4\.\s*Main Issue\s*/\s*Topic",
        r"##\s*5\.\s*Impact\s*/\s*Significance"
    )

    impact = extract_section(
        r"##\s*5\.\s*Impact\s*/\s*Significance",
        r"##\s*6\.\s*Recommended Actions"
    )

    actions = extract_section(
        r"##\s*6\.\s*Recommended Actions",
        r"##\s*7\.\s*Key Takeaway"
    )

    takeaway = extract_section(
        r"##\s*7\.\s*Key Takeaway",
        r"##\s*8\.\s*Layout Recommendation"
    )

    title = clean_text(title, 120)
    key_message = clean_text(key_message, 220)
    key_facts = clean_text(key_facts, 500)
    main_issue = clean_text(main_issue, 220)
    impact = clean_text(impact, 400)
    actions = clean_text(actions, 400)
    takeaway = clean_text(takeaway, 220)

    if not title:
        title = "AI-Generated Infographic"

    if not key_message:
        key_message = "Key message derived from the supplied source."

    if not key_facts:
        key_facts = "Key facts derived from the supplied source."

    if not main_issue:
        main_issue = "Main topic derived from the supplied source."

    if not impact:
        impact = "Impact based on the supplied source."

    if not actions:
        actions = "Recommended actions based on the supplied source."

    if not takeaway:
        takeaway = "Key takeaway derived from the supplied source."

    modifications = {
        "objects": [
            {
                "name": "title",
                "text": title
            },
            {
                "name": "subtitle",
                "text": key_message
            },
            {
                "name": "section_1_heading",
                "text": "Key Facts"
            },
            {
                "name": "section_1_content",
                "text": key_facts
            },
            {
                "name": "section_2_heading",
                "text": "Main Topic"
            },
            {
                "name": "section_2_content",
                "text": main_issue
            },
            {
                "name": "section_3_heading",
                "text": "Impact & Actions"
            },
            {
                "name": "section_3_content",
                "text": f"Impact: {impact} Actions: {actions}"
            },
            {
                "name": "takeaway_heading",
                "text": "Key Takeaway"
            },
            {
                "name": "takeaway_content",
                "text": takeaway
            },
            {
                "name": "footer",
                "text": "SIH26154 • Team NEX GEN"
            }
        ]
    }

    response = requests.post(
        f"{BANNERBEAR_API_BASE}/images",
        headers={
            "Authorization": f"Bearer {BANNERBEAR_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "template": BANNERBEAR_TEMPLATE_UID,
            "formats": ["png"],
            "modifications": modifications,
        },
        timeout=60,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Bannerbear error {response.status_code}: "
            f"{response.text[:500]}"
        )

    data = response.json()

    if not data.get("files", {}).get("png"):
        raise RuntimeError(
            f"Bannerbear did not return a PNG file: {data}"
        )

    return data
# =========================================================
# SPECIALIST AI ROUTER
# =========================================================

def generate_single_content(
    request: ContentRequest,
    output: str
):

    single_request = request.model_copy(
        update={
            "outputs": [output]
        }
    )

    prompt = build_prompt(
        single_request
    )

    # =====================================================
    # SPECIALIST ROUTING MAP
    # =====================================================

    output_key = (
        output.strip().lower()
    )

    output_key_map = {

        "executive summary": "summary",

        "summary": "summary",

        "advisory": "advisory",

        "linkedin post": "linkedin",

        "linkedin": "linkedin",

        "twitter / x": "twitter",

        "twitter/x": "twitter",

        "twitter": "twitter",

        "x": "twitter",

        "infographic": "infographic",

        "presentation": "presentation",

        "video package": "video_package",

        "video_package": "video_package",
    }

    output_key = output_key_map.get(
        output_key,
        output_key
    )

    specialist = {

        "summary":
            "Summary Specialist",

        "advisory":
            "Advisory Specialist",

        "linkedin":
            "Social Media Specialist",

        "twitter":
            "Social Media Specialist",

        "infographic":
            "Visual Content Specialist",

        "presentation":
            "Presentation Specialist",

        "video_package":
            "Video Content Specialist",

    }.get(
        output_key,
        "General Content Specialist"
    )

    print(
        f"Routing '{output}' → {specialist}"
    )

    # =====================================================
    # PRESENTATION
    # PRIMARY: GROQ
    # FALLBACK: GEMINI → OPENROUTER
    # =====================================================

    if output_key == "presentation":

        try:

            content = generate_with_groq(
                prompt
            )

            return {
                "content": content,
                "provider": "Groq",
                "specialist": specialist,
                "fallback": False
            }

        except Exception as groq_error:

            print(
                "Groq presentation generation failed:",
                groq_error
            )

            try:

                content = generate_with_gemini(
                    prompt
                )

                return {
                    "content": content,
                    "provider": "Gemini",
                    "specialist": specialist,
                    "fallback": True
                }

            except Exception as gemini_error:

                print(
                    "Gemini presentation generation failed:",
                    gemini_error
                )

                try:

                    content = generate_with_openrouter(
                        prompt
                    )

                    return {
                        "content": content,
                        "provider": "OpenRouter",
                        "specialist": specialist,
                        "fallback": True
                    }

                except Exception as openrouter_error:

                    print(
                        "OpenRouter presentation generation failed:",
                        openrouter_error
                    )

                    raise HTTPException(
                        status_code=503,
                        detail=(
                            "Groq, Gemini and OpenRouter "
                            "failed to generate the presentation outline."
                        )
                    )

    # =====================================================
    # SUMMARY / ADVISORY
    # PRIMARY: GEMINI
    # FALLBACK: GROQ → OPENROUTER
    # =====================================================

    if output_key in [
        "summary",
        "advisory"
    ]:

        try:

            content = generate_with_gemini(
                prompt
            )

            return {
                "content": content,
                "provider": "Gemini",
                "specialist": specialist,
                "fallback": False
            }

        except Exception as gemini_error:

            print(
                "Gemini failed:",
                gemini_error
            )

            print(
                "Trying Groq fallback..."
            )

            try:

                content = generate_with_groq(
                    prompt
                )

                return {
                    "content": content,
                    "provider": "Groq",
                    "specialist": specialist,
                    "fallback": True
                }

            except Exception as groq_error:

                print(
                    "Groq failed:",
                    groq_error
                )

                print(
                    "Trying OpenRouter fallback..."
                )

                try:

                    content = generate_with_openrouter(
                        prompt
                    )

                    return {
                        "content": content,
                        "provider": "OpenRouter",
                        "specialist": specialist,
                        "fallback": True
                    }

                except Exception as openrouter_error:

                    print(
                        "OpenRouter failed:",
                        openrouter_error
                    )

                    raise HTTPException(
                        status_code=503,
                        detail=(
                            "Gemini, Groq and OpenRouter "
                            "failed to generate content."
                        )
                    )

    # =====================================================
    # INFOGRAPHIC
    # PRIMARY: GROQ + BANNERBEAR
    # FALLBACK: GEMINI + BANNERBEAR
    if output_key == "infographic":
     try:
        content = generate_with_groq(prompt)

        infographic_path = generate_html_infographic(content)

        return {
            "content": content,
           "image_url": "http://127.0.0.1:8000/generated-infographics/infographic.png",
            "format": "png",
            "provider": "Groq + HTML Renderer",
            "specialist": specialist,
            "fallback": False
        }

     except Exception as groq_error:
        print(
            "Groq + HTML infographic generation failed:",
            groq_error
        )

        try:
            content = generate_with_gemini(prompt)

            infographic_path = generate_html_infographic(content)

            return {
                "content": content,
                "image_url": "/generated-infographics/infographic.png",
                "format": "png",
                "provider": "Gemini + HTML Renderer",
                "specialist": specialist,
                "fallback": True
            }

        except Exception as gemini_error:
            print(
                "Gemini + HTML infographic generation failed:",
                gemini_error
            )

            raise HTTPException(
                status_code=503,
                detail=(
                    "Infographic generation failed. "
                    f"Groq/HTML: {groq_error}; "
                    f"Gemini/HTML: {gemini_error}"
                )
            )
    # OTHER OUTPUTS
    # PRIMARY: GROQ
    # FALLBACK: GEMINI → OPENROUTER
    # =====================================================

    try:

        content = generate_with_groq(
            prompt
        )

        return {
            "content": content,
            "provider": "Groq",
            "specialist": specialist,
            "fallback": False
        }

    except Exception as groq_error:

        print(
            "Groq failed:",
            groq_error
        )

        print(
            "Trying Gemini fallback..."
        )

        try:

            content = generate_with_gemini(
                prompt
            )

            return {
                "content": content,
                "provider": "Gemini",
                "specialist": specialist,
                "fallback": True
            }

        except Exception as gemini_error:

            print(
                "Gemini failed:",
                gemini_error
            )

            print(
                "Trying OpenRouter fallback..."
            )

            try:

                content = generate_with_openrouter(
                    prompt
                )

                return {
                    "content": content,
                    "provider": "OpenRouter",
                    "specialist": specialist,
                    "fallback": True
                }

            except Exception as openrouter_error:

                print(
                    "OpenRouter failed:",
                    openrouter_error
                )

                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Groq, Gemini and OpenRouter "
                        "failed to generate content."
                    )
                )


# =========================================================
# GENERATE MULTIPLE OUTPUTS
# =========================================================

def generate_content(
    request: ContentRequest
):

    outputs = (
        request.outputs
        or ["summary"]
    )

    results = []

    providers = []

    fallback_used = False

    for output in outputs:

        result = generate_single_content(
            request,
            output
        )

        results.append(
            {
                "type": output,
                "content": result["content"],
                "image_url": result.get(
                    "image_url"
                ),
                "format": result.get(
                    "format"
                )
            }
        )

        providers.append(
            result["provider"]
        )

        if result["fallback"]:
            fallback_used = True

    return {
        "content": results,
        "provider": ", ".join(
            dict.fromkeys(providers)
        ),
        "fallback": fallback_used
    }


# =========================================================
# LOCAL PRESENTATION PPTX GENERATOR
# =========================================================

def create_presentation_pptx(
    content: str
):

    prs = Presentation()

    # =====================================================
    # TITLE SLIDE
    # =====================================================

    title_slide = prs.slides.add_slide(
        prs.slide_layouts[0]
    )

    title_slide.shapes.title.text = (
        "Generated Presentation"
    )

    if len(title_slide.placeholders) > 1:

        for placeholder in title_slide.placeholders:

            if (
                placeholder.placeholder_format.idx
                == 1
            ):

                placeholder.text = (
                    "SIH26154 – "
                    "GenAI Content Transformation"
                )

    # =====================================================
    # CONTENT SLIDES
    # =====================================================

    sections = re.split(
        r"\n\s*\n",
        content.strip()
    )

    for section in sections:

        if not section.strip():
            continue

        lines = [
            line.strip()
            for line in section.splitlines()
            if line.strip()
        ]

        if not lines:
            continue

        slide = prs.slides.add_slide(
            prs.slide_layouts[1]
        )

        slide.shapes.title.text = (
            lines[0][:100]
        )

        body = (
            slide.placeholders[1]
            .text_frame
        )

        body.clear()

        for line in lines[1:]:

            clean_line = re.sub(
                r"^[#*\-\d.\s]+",
                "",
                line
            ).strip()

            if not clean_line:
                continue

            paragraph = (
                body.add_paragraph()
            )

            paragraph.text = clean_line

            paragraph.level = 0

    # =====================================================
    # SAVE
    # =====================================================

    output = io.BytesIO()

    prs.save(output)

    output.seek(0)

    return output


# =========================================================
# YOUTUBE EXTRACTION API
# =========================================================

@app.post("/extract-youtube")
def extract_youtube(
    url: str = Form(...)
):

    if not url.strip():

        raise HTTPException(
            status_code=400,
            detail="YouTube URL is required."
        )

    try:

        text = extract_youtube_transcript(
            url.strip()
        )

        return {
            "status": "success",
            "source_type": "youtube",
            "text": text,
            "character_count": len(text)
        }

    except ValueError as error:

        raise HTTPException(
            status_code=400,
            detail=str(error)
        )

    except HTTPException:

        raise

    except Exception as error:

        print(
            "YouTube extraction failed:",
            error
        )

        raise HTTPException(
            status_code=422,
            detail=str(error)
        )

# =========================================================
# WEB / ARTICLE EXTRACTION API
# =========================================================

@app.post("/extract-web")
def extract_web(
    url: str = Form(...)
):

    if not url.strip():

        raise HTTPException(
            status_code=400,
            detail="Webpage URL is required."
        )

    try:

        response = requests.get(
            url.strip(),
            timeout=20,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        html = response.text

        text = re.sub(
            r"<script.*?</script>",
            " ",
            html,
            flags=re.DOTALL | re.IGNORECASE
        )

        text = re.sub(
            r"<style.*?</style>",
            " ",
            text,
            flags=re.DOTALL | re.IGNORECASE
        )

        text = re.sub(
            r"<[^>]+>",
            " ",
            text
        )

        text = re.sub(
            r"\s+",
            " ",
            text
        ).strip()

        if not text:
            raise RuntimeError(
                "No readable content was found on this webpage."
            )

        return {
            "status": "success",
            "source_type": "web",
            "url": url.strip(),
            "text": text,
            "character_count": len(text)
        }

    except Exception as error:

        print(
            "Web extraction failed:",
            error
        )

        raise HTTPException(
            status_code=422,
            detail=str(error)
        )
# =========================================================
# FILE EXTRACTION API
# =========================================================
@app.post("/extract-file")
async def extract_file(
    file: UploadFile = File(...)
):

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file selected."
        )

    allowed = (
        ".pdf",
        ".docx",
        ".txt",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".webm",
        ".m4v"
    )

    if not file.filename.lower().endswith(allowed):
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. "
                "Use PDF, DOCX, TXT, images or videos."
            )
        )

    try:

        data = await file.read()

        if not data:
            raise HTTPException(
                status_code=400,
                detail="The uploaded file is empty."
            )

        filename = file.filename.lower()

        if filename.endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".gif")
        ):
            text = extract_image_content(
                file.filename,
                data
            )

        elif filename.endswith(
            (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v")
        ):
            text = extract_video_audio_text(
                file.filename,
                data
            )

        else:
            text = extract_uploaded_file(
                file,
                data
            )

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

        print(
            "File extraction failed:",
            error
        )

        raise HTTPException(
            status_code=422,
            detail=str(error)
        )

# =========================================================
# TRANSFORM API
# =========================================================

@app.post("/transform")
def transform_content(
    request: ContentRequest
):

    if not request.text.strip():

        raise HTTPException(
            status_code=400,
            detail="Source text cannot be empty."
        )

    result = generate_content(
        request
    )

    return {
        "status": "success",
        "generated_content": result["content"],
        "provider": result["provider"],
        "fallback_used": result["fallback"]
    }


# =========================================================
# PRESENTATION EXPORT API
# =========================================================

@app.post("/export/presentation")
def export_presentation(
    request: PresentationExportRequest
):

    if not request.content.strip():

        raise HTTPException(
            status_code=400,
            detail=(
                "Presentation content "
                "cannot be empty."
            )
        )

    # =====================================================
    # PRIMARY: SLIDEFORGE
    # FALLBACK: python-pptx
    # =====================================================

    if SLIDEFORGE_API_KEY:

        try:

            export_request = ContentRequest(
                text=request.content,
                outputs=["Presentation"]
            )

            job_id, metadata = (
                generate_presentation_with_slideforge(
                    request.content,
                    export_request
                )
            )

            print(
                "SlideForge Presentation "
                f"Specialist completed job {job_id}. "
                f"Slides: "
                f"{len(metadata.get('slides', []))}, "
                f"Cost: "
                f"{metadata.get('cost', 'unknown')}"
            )

            pptx_file = (
                download_slideforge_pptx(
                    job_id
                )
            )

            return StreamingResponse(
                pptx_file,
                media_type=(
                    "application/vnd.openxmlformats-"
                    "officedocument.presentationml.presentation"
                ),
                headers={
                    "Content-Disposition":
                    (
                        "attachment; "
                        "filename=generated_presentation.pptx"
                    )
                },
            )

        except Exception as slideforge_error:

            print(
                "SlideForge Presentation "
                "Specialist failed:",
                slideforge_error
            )

            print(
                "Falling back to local "
                "python-pptx generator..."
            )

    # =====================================================
    # LOCAL FALLBACK
    # =====================================================

    pptx_file = create_presentation_pptx(
        request.content
    )

    return StreamingResponse(
        pptx_file,
        media_type=(
            "application/vnd.openxmlformats-"
            "officedocument.presentationml.presentation"
        ),
        headers={
            "Content-Disposition":
            (
                "attachment; "
                "filename=generated_presentation.pptx"
            )
        },
    )


# =========================================================
# BANNERBEAR TEST API
# =========================================================

@app.post("/test-bannerbear")
def test_bannerbear():

    return generate_bannerbear_infographic_test()