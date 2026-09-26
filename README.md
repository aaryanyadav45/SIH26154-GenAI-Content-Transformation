SIH26154 – Gen AI Platform for Automated Content Transformation

Project Overview:

SIH26154 is a Generative AI platform that transforms source content into multiple useful output formats. It accepts content from text, YouTube URLs, webpage/article URLs, and uploaded documents, extracts the relevant information, and uses AI to generate structured, audience-specific content.

Input Sources:

- Pasted text
- YouTube URLs
- Webpage and article URLs
- Uploaded TXT, PDF, and DOCX files
- Images and scanned PDFs using OCR

Output Formats:

- Executive Summary
- Cybersecurity Advisory
- LinkedIn Post
- X/Twitter Thread
- Presentation
- Infographic
- Video Package

Key Features:

- Multi-source content extraction
- AI-powered content transformation
- Multiple AI provider support with fallback
- Audience, tone, language, and detail customization
- OCR support for images and scanned PDFs
- Presentation generation
- Infographic generation
- Video content package generation
- Web-based user interface
- FastAPI backend with React frontend

Technology Stack:

Frontend:

- React
- Vite
- JavaScript
- CSS

Backend:

- Python
- FastAPI

AI and Processing:

- Google Gemini
- Groq
- OpenRouter
- OCR with Tesseract
- PDF/DOCX/TXT text extraction
- Webpage extraction using Playwright
- YouTube transcript extraction

Content Generation:

- SlideForge for presentation generation
- HTML/CSS-based infographic generation

Setup Instructions:

Backend Setup:

1. Create a Python virtual environment:

python -m venv venv

2. Activate the virtual environment on Windows:

venv\Scripts\activate

3. Install the required Python packages:

pip install -r requirements.txt

4. Install the Playwright browser:

playwright install

5. For OCR support, install Tesseract OCR separately on the system and make sure the Tesseract executable is available to the application.

6. Create a .env file inside the Backend folder and add the required API keys.

The following environment variables are required:

GEMINI_API_KEY
GROQ_API_KEY
OPENROUTER_API_KEY
SLIDEFORGE_API_KEY
SLIDEFORGE_THEME_ID

Do not upload the .env file to GitHub or expose any API keys publicly.

7. Start the backend server:

uvicorn main:app --reload --port 8000

The backend will run at:

http://127.0.0.1:8000

Frontend Setup:

1. Install the frontend dependencies:

npm install

2. Start the frontend development server:

npm run dev

3. Open the local URL shown by Vite in the terminal.

How It Works:

1. User provides source content through text, a YouTube URL, a webpage/article URL, or an uploaded file.
2. The platform extracts and preprocesses the source content.
3. AI processes the content according to the selected audience, tone, language, and detail preferences.
4. The transformed content is returned in the selected output formats.

Source Code:

GitHub Repository:

https://github.com/aaryanyadav45/SIH26154-GenAI-Content-Transformation

Project Status:

Prototype completed for SIH 2026 evaluation.