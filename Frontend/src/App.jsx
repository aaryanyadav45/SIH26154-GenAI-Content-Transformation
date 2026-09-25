import { useState } from 'react'
import {
  FileText,
  Sparkles,
  Settings2,
  Upload,
  WandSparkles,
} from 'lucide-react'

const API_BASE_URL = 'http://127.0.0.1:8000'
function App() {
    const [selectedOutputs, setSelectedOutputs] = useState([])
    const [sourceContent, setSourceContent] = useState('')
    const [language, setLanguage] = useState('English')
    const [audience, setAudience] = useState('General audience')
    const [tone, setTone] = useState('Professional')
    const [detailLevel, setDetailLevel] = useState('Standard')
    const [objective, setObjective] = useState('Inform')
    const [contentStyle, setContentStyle] = useState('Standard')
    const [isTransforming, setIsTransforming] = useState(false)
    const [copiedOutput, setCopiedOutput] = useState('')
    const [generatedResults, setGeneratedResults] = useState([])
    const [error, setError] = useState('')
    const [webUrl, setWebUrl] = useState('')
    const [isUploading, setIsUploading] = useState(false)
    const [isYouTubeExtracting, setIsYouTubeExtracting] = useState(false)
    const [youtubeUrl, setYoutubeUrl] = useState('')
      const handleTransform = async () => {
    setError('')
    setGeneratedResults([])

    if (!sourceContent.trim()) {
      setError('Please provide source content before transforming.')
      return
    }

    if (selectedOutputs.length === 0) {
      setError('Please select at least one output deliverable.')
      return
    }

    setIsTransforming(true)

    try {
      const response = await fetch(`${API_BASE_URL}/transform`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
         text: sourceContent,
          outputs: selectedOutputs,
          audience,
          tone,
          language,
     detail: detailLevel,
          objective,
          content_style: contentStyle,
        }),
      })

      if (!response.ok) {
        throw new Error(`Backend request failed: ${response.status}`)
      }

    const data = await response.json()

console.log('Backend response:', data)
setGeneratedResults(
  Array.isArray(data.generated_content)
    ? data.generated_content
    : [
        {
          type: selectedOutputs[0],
          content: data.generated_content,
        },
      ]
)
    } catch (err) {
      console.error(err)
      setError('Unable to connect to the AI backend.')
    } finally {
      setIsTransforming(false)
    }
  }
  const handleFileUpload = async (event) => {
  const file = event.target.files?.[0]

  if (!file) return

  setError('')
  setIsUploading(true)

  try {
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(
      `${API_BASE_URL}/extract-file`,
      {
        method: 'POST',
        body: formData,
      }
    )

    if (!response.ok) {
      throw new Error(`File upload failed: ${response.status}`)
    }

    const data = await response.json()

    setSourceContent(
      data.text ||
      data.extracted_text ||
      ''
    )
  } catch (err) {
    console.error('File upload error:', err)
    setError('Failed to extract content from the uploaded file.')
  } finally {
    setIsUploading(false)
    event.target.value = ''
  }
}
  const handleDownloadPptx = async (content) => {
  try {
    const response = await fetch(
      `${API_BASE_URL}/export/presentation`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content,
        }),
      }
    )

    if (!response.ok) {
      throw new Error('Failed to generate PPTX')
    }

    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)

    const link = document.createElement('a')
    link.href = url
    link.download = 'generated_presentation.pptx'
    document.body.appendChild(link)
    link.click()
    link.remove()

    window.URL.revokeObjectURL(url)
  } catch (error) {
    console.error('PPTX download error:', error)
    setError('Failed to download PowerPoint file.')
  }
}
const handleYouTubeExtract = async () => {
  if (!youtubeUrl.trim()) {
    setError('Please enter a YouTube URL.')
    return
  }

  setError('')
 setIsYouTubeExtracting(true)
  try {
   const formData = new FormData()
formData.append('url', youtubeUrl)

const response = await fetch(
  `${API_BASE_URL}/extract-youtube`,
  {
    method: 'POST',
    body: formData,
  }
)

    if (!response.ok) {
      throw new Error(`YouTube extraction failed: ${response.status}`)
    }

    const data = await response.json()

    setSourceContent(
      data.text ||
      data.transcript ||
      data.extracted_text ||
      ''
    )
  } catch (err) {
    console.error('YouTube extraction error:', err)
    setError('Failed to extract content from YouTube.')
  } finally {
  setIsYouTubeExtracting(false)
}
}
const handleWebExtract = async () => {
  if (!webUrl.trim()) {
    setError('Please enter a webpage URL.')
    return
  }

  setError('')
  setIsUploading(true)

  try {
    const formData = new FormData()
    formData.append('url', webUrl)

    const response = await fetch(
      `${API_BASE_URL}/extract-web`,
      {
        method: 'POST',
        body: formData,
      }
    )

    if (!response.ok) {
      throw new Error(`Web extraction failed: ${response.status}`)
    }

    const data = await response.json()

    setSourceContent(
      data.text ||
      data.extracted_text ||
      ''
    )
  } catch (err) {
    console.error('Web extraction error:', err)
    setError('Failed to extract content from webpage.')
  } finally {
    setIsUploading(false)
  }
}
  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* Header */}
      <header className="border-b border-white/10 bg-slate-950/90">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <div>
            <h1 className="text-xl font-semibold">
              GenAI Content Transformation
            </h1>
            <p className="mt-1 text-sm text-slate-400">
              SIH26154 • AI-powered content transformation platform
            </p>
          </div>

          <div className="flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-4 py-2 text-sm text-cyan-300">
            <Sparkles size={16} />
            AI Engine
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="mx-auto max-w-7xl px-6 py-10">
        <div className="mb-8">
          <h2 className="text-3xl font-bold tracking-tight">
            Transform your content
          </h2>
          <p className="mt-2 max-w-2xl text-slate-400">
            Submit a common source, configure your communication requirements,
            and generate multiple professional deliverables from one workflow.
          </p>
        </div>

        <div className="grid gap-6 lg:grid-cols-3">
          {/* Source */}
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 lg:col-span-2">
            <div className="mb-5 flex items-center gap-3">
              <div className="rounded-xl bg-cyan-400/10 p-3 text-cyan-300">
                <FileText size={20} />
              </div>

              <div>
                <h3 className="font-semibold">Source content</h3>
                <p className="text-sm text-slate-400">
                  Provide the information you want to transform
                </p>
              </div>
            </div>

           <textarea
 className="h-64 w-full resize-none rounded-2xl border border-white/10 bg-slate-950/70 p-5 text-sm leading-6 text-white outline-none transition placeholder:text-slate-500 focus:border-cyan-400/50 focus:ring-1 focus:ring-cyan-400/20"
 placeholder="Paste your source content here..."
  value={sourceContent}
  onChange={(event) => setSourceContent(event.target.value)}
/>
<label className="mt-4 inline-flex cursor-pointer items-center gap-2 rounded-xl border border-cyan-400/20 bg-cyan-400/10 px-4 py-3 text-sm font-medium text-cyan-200 transition hover:bg-cyan-400/20">
  <Upload size={17} />

  {isUploading ? 'Extracting...' : 'Upload File'}

  <input
    type="file"
    className="hidden"
    accept=".pdf,.docx,.txt,.png,.jpg,.jpeg"
    onChange={handleFileUpload}
  />
</label>
<div className="mt-4 flex gap-2">
  <input
    type="text"
    value={youtubeUrl}
    onChange={(event) => setYoutubeUrl(event.target.value)}
   placeholder="Paste a YouTube URL..."
    className="flex-1 rounded-xl border border-white/10 bg-slate-900 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-400/50"
  />

  <button
    type="button"
    onClick={handleYouTubeExtract}
disabled={isYouTubeExtracting}
    className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium transition hover:bg-white/10 disabled:opacity-50"
  >
   {isYouTubeExtracting ? 'Extracting...' : 'Extract YouTube URL'}
  </button>
</div>
<div className="mt-4 flex gap-2">
  <input
    type="text"
    value={webUrl}
    onChange={(event) => setWebUrl(event.target.value)}
    placeholder="Paste a webpage or article URL..."
    className="flex-1 rounded-xl border border-white/10 bg-slate-900 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-400/50"
  />
<button
  type="button"
  onClick={handleWebExtract}
  className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium transition hover:bg-white/10"
>
  Extract Web Content
</button>
</div>
          </section>

          {/* Configuration */}
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-6">
            <div className="mb-5 flex items-center gap-3">
              <div className="rounded-xl bg-violet-400/10 p-3 text-violet-300">
                <Settings2 size={20} />
              </div>

              <div>
                <h3 className="font-semibold">Content settings</h3>
                <p className="text-sm text-slate-400">
                  Control the generated content
                </p>
              </div>
            </div>

            <div className="space-y-4">
              <label className="block">
                <span className="mb-2 block text-sm text-slate-400">
                  Target audience
                </span>
                <select
  className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-sm outline-none"
  value={audience}
  onChange={(event) => setAudience(event.target.value)}
>
                  <option>General audience</option>
                  <option>Students</option>
                  <option>Professionals</option>
                  <option>Executives</option>
                  <option>Technical audience</option>
                </select>
              </label>

              <label className="block">
                <span className="mb-2 block text-sm text-slate-400">
                  Tone
                </span>
                <select
  className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-sm outline-none"
  value={tone}
  onChange={(event) => setTone(event.target.value)}
>
                  <option>Professional</option>
                  <option>Simple</option>
                  <option>Formal</option>
                  <option>Friendly</option>
                  <option>Persuasive</option>
                </select>
              </label>

             <label className="block">
  <span className="mb-2 block text-sm text-slate-400">
    Language
  </span>

  <select
  className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-sm outline-none"
  value={language}
  onChange={(event) => setLanguage(event.target.value)}
>
    <option>English</option>
    <option>Assamese</option>
    <option>Bengali</option>
    <option>Bodo</option>
    <option>Dogri</option>
    <option>Gujarati</option>
    <option>Hindi</option>
    <option>Kannada</option>
    <option>Kashmiri</option>
    <option>Konkani</option>
    <option>Maithili</option>
    <option>Malayalam</option>
    <option>Manipuri (Meitei)</option>
    <option>Marathi</option>
    <option>Nepali</option>
    <option>Odia</option>
    <option>Punjabi</option>
    <option>Sanskrit</option>
    <option>Santali</option>
    <option>Sindhi</option>
    <option>Tamil</option>
    <option>Telugu</option>
    <option>Urdu</option>
  </select>
</label>

              <label className="block">
                <span className="mb-2 block text-sm text-slate-400">
                  Level of detail
                </span>
               <select
  className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-sm outline-none"
  value={detailLevel}
  onChange={(event) => setDetailLevel(event.target.value)}
>
                  <option>Standard</option>
                  <option>Concise</option>
                  <option>Detailed</option>
                </select>
              </label>
              <label className="block">
  <span className="mb-2 block text-sm text-slate-400">
    Communication objective
  </span>

 <select
  className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-sm outline-none"
  value={objective}
  onChange={(event) => setObjective(event.target.value)}
>
    <option>Inform</option>
    <option>Educate</option>
    <option>Persuade</option>
    <option>Summarize</option>
    <option>Engage</option>
  </select>
</label>
<label className="block">
  <span className="mb-2 block text-sm text-slate-400">
    Content style
  </span>

  <select
  className="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-3 text-sm outline-none"
  value={contentStyle}
  onChange={(event) => setContentStyle(event.target.value)}
>
    <option>Standard</option>
    <option>Professional</option>
    <option>Storytelling</option>
    <option>Technical</option>
    <option>Conversational</option>
    <option>Educational</option>
    <option>News / Journalistic</option>
  </select>
</label>
            </div>
          </section>
        </div>

        {/* Outputs */}
        <section className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-6">
          <div className="mb-5">
            <h3 className="font-semibold">Output deliverables</h3>
            <p className="mt-1 text-sm text-slate-400">
              Select one or more formats to generate from the same source.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              'Executive Summary',
              'Advisory',
              'LinkedIn Post',
              'Twitter / X',
              'Infographic',
              'Presentation',
              'Video Package',
          
            ].map((output) => (
              <label
                key={output}
                className="flex cursor-pointer items-center gap-3 rounded-xl border border-white/10 bg-slate-900/70 p-4 transition hover:border-cyan-400/30 hover:bg-white/5"
              >
                <input
  type="checkbox"
  className="h-4 w-4 accent-cyan-400"
  checked={selectedOutputs.includes(output)}
  onChange={() => {
    setSelectedOutputs((current) =>
      current.includes(output)
        ? current.filter((item) => item !== output)
        : [...current, output]
    )
  }}
/>
                <span className="text-sm">{output}</span>
              </label>
            ))}
          </div>
{!sourceContent.trim() && (
  <p className="mt-3 text-center text-xs text-slate-500">
    Please provide source content.
  </p>
)}

{sourceContent.trim() && selectedOutputs.length === 0 && (
  <p className="mt-3 text-center text-xs text-slate-500">
    Select at least one deliverable.
  </p>
)}
   <button
  onClick={handleTransform}
  disabled={isTransforming}disabled={isTransforming || !sourceContent.trim() || selectedOutputs.length === 0}
  className="mt-6 flex w-full items-center justify-center gap-2 rounded-2xl bg-cyan-400 px-6 py-4 text-sm font-semibold text-slate-950 shadow-lg transition hover:bg-cyan-300 hover:shadow-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-50"
>
 {isTransforming ? (
  <>
    <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-950 border-t-transparent" />
  Generating deliverables...
  </>
) : (
  <>
    <WandSparkles size={18} />
    Transform Content
  </>
)}
</button>
        </section>
                {/* Results */}
        <section className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-6">
          <div className="mb-5">
           <h3 className="text-xl font-semibold text-white">
  Generated deliverables
</h3>
            <p className="mt-1 text-sm text-slate-400">
              Your transformed content will appear here.
            </p>
            {generatedResults.length > 0 && (
  <div className="mt-3 rounded-xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-300">
    ✓ Transformation completed successfully — {generatedResults.length} deliverable{generatedResults.length === 1 ? '' : 's'} generated.
  </div>
)}
          </div>

          <div className="space-y-4">
        {error && (
  <div className="rounded-xl border border-red-400/20 bg-red-400/10 p-4 text-sm text-red-300">
    {error}
  </div>
)}  
{selectedOutputs.length > 0 && (
  <p className="mb-4 text-sm text-slate-400">
    {selectedOutputs.length} output{selectedOutputs.length === 1 ? '' : 's'} selected
  </p>
)} 
 {generatedResults.length === 0 ? (
  <div className="rounded-xl border border-dashed border-white/10 bg-slate-900/50 p-8 text-center">
    <Sparkles className="mx-auto mb-3 text-cyan-300" size={28} />

    <p className="text-sm text-slate-400">
   No deliverables generated yet.
    </p>

   <p className="mt-1 text-xs leading-5 text-slate-500">
  Select your deliverables and configure the options above, then click Transform Content.
</p>
  </div>
) : (
  generatedResults.map((result) => (
  <div
  key={result.type}
  className="rounded-2xl border border-white/10 bg-slate-900/70 p-6 shadow-lg"
>
   <h4 className="text-lg font-semibold text-white">
  {result.type}
</h4>

      {result.image_url ? (
        <img
          src={result.image_url}
          alt={`${result.type} preview`}
          className="mx-auto mt-4 max-h-[850px] w-auto max-w-full rounded-xl border border-white/10 object-contain"
        />
      ) : (
       <div className="mt-4 rounded-lg border border-white/5 bg-slate-950/40 p-4">
  <p className="whitespace-pre-wrap text-sm leading-6 text-slate-300">
    {result.content}
  </p>
</div>
      )}
  {result.type === 'Executive Summary' && (
        <button
          type="button"
          onClick={async () => {
            await navigator.clipboard.writeText(result.content)
            setCopiedOutput(result.type)

            setTimeout(() => {
              setCopiedOutput('')
            }, 2500)
          }}
          className="mt-4 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold transition hover:bg-white/10"
        >
          {copiedOutput === result.type ? 'Copied ✓' : 'Copy'}
        </button>
      )}

      {result.type === 'Advisory' && (
        <button
          type="button"
          onClick={async () => {
            await navigator.clipboard.writeText(result.content)
            setCopiedOutput(result.type)

            setTimeout(() => {
              setCopiedOutput('')
            }, 2500)
          }}
          className="mt-4 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold transition hover:bg-white/10"
        >
          {copiedOutput === result.type ? 'Copied ✓' : 'Copy'}
        </button>
      )}

      {result.type === 'LinkedIn Post' && (
        <button
          type="button"
          onClick={async () => {
            await navigator.clipboard.writeText(result.content)
            setCopiedOutput(result.type)

            setTimeout(() => {
              setCopiedOutput('')
            }, 2500)
          }}
          className="mt-4 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold transition hover:bg-white/10"
        >
          {copiedOutput === result.type ? 'Copied ✓' : 'Copy'}
        </button>
      )}

      {result.type === 'Twitter / X' && (
        <button
          type="button"
          onClick={async () => {
            await navigator.clipboard.writeText(result.content)
            setCopiedOutput(result.type)

            setTimeout(() => {
              setCopiedOutput('')
            }, 2500)
          }}
          className="mt-4 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold transition hover:bg-white/10"
        >
          {copiedOutput === result.type ? 'Copied ✓' : 'Copy'}
        </button>
      )}

      {result.type === 'Video Package' && (
        <button
          type="button"
          onClick={async () => {
            await navigator.clipboard.writeText(result.content)
            setCopiedOutput(result.type)

            setTimeout(() => {
              setCopiedOutput('')
            }, 2500)
          }}
          className="mt-4 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold transition hover:bg-white/10"
        >
          {copiedOutput === result.type ? 'Copied ✓' : 'Copy'}
        </button>
      )}

      {result.type === 'Infographic' && result.image_url && (
        <a
          href={result.image_url}
          download="infographic.png"
          className="mt-4 inline-block rounded-lg bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300"
        >
          Download PNG
        </a>
      )}

      {result.type === 'Presentation' && (
        <button
          type="button"
          onClick={() => handleDownloadPptx(result.content)}
          className="mt-4 rounded-lg bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300"
        >
          Download PPTX
        </button>
      )}
    </div>
  ))
)}
</div>
      </section>
    </main>
  </div>
)
}

export default App