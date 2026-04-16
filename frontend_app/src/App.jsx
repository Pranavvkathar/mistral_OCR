import React, { useState, useCallback, useEffect, useRef } from 'react';
import axios from 'axios';
import { useDropzone } from 'react-dropzone';
import {
  Upload, FileText, CheckCircle2, AlertCircle, Loader2, ChevronRight, Eye,
  Download, Clock, Menu, Plus, ScanText, FileCog, DatabaseZap, FileOutput,
  Table2, AlignLeft, ChevronDown, ChevronUp, ImageIcon, Layout, Play, FileJson,
  Code, RotateCcw, PlusCircle, Home, Layers, Zap, Mic, Settings, MoreVertical,
  Minus, Maximize2, RotateCw, Search, ExternalLink, Link as LinkIcon, Copy
} from 'lucide-react';
import PdfAnnotationViewer from './PdfAnnotationViewer';

const API_BASE = '/api';

// ── Helpers ───────────────────────────────────────────────────────────────────

function getFileStats(file, stats) {
  if (!file) return null;
  const size = file.size ? (file.size / (1024 * 1024)).toFixed(2) + 'MB' : '0MB';
  const pages = stats?.pages || '?';
  const time = stats?.time_taken ? stats.time_taken + 's' : '?';
  const cost = stats?.cost ? '$' + stats.cost : '?';
  return { size, pages, time, cost };
}

// ── Main App ──────────────────────────────────────────────────────────────────

function App() {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [highlightedPdfUrl, setHighlightedPdfUrl] = useState(null);
  const [localPdfUrl, setLocalPdfUrl] = useState(null);
  const [annotations, setAnnotations] = useState(null);
  const [stats, setStats] = useState(null);
  const [markdownText, setMarkdownText] = useState('');
  const [activeTab, setActiveTab] = useState('text');
  const [mainTab, setMainTab] = useState('configure');

  const [reportsList, setReportsList] = useState([]);
  const [selectedReportId, setSelectedReportId] = useState(null);

  // 📝 Advanced OCR Configuration State
  const [config, setConfig] = useState({
    tableFormat: 'null',
    confidenceLevel: 'null',
    extractHeader: false,
    extractFooter: false,
  });

  // Local PDF preview for un-processed uploads
  useEffect(() => {
    if (file && file instanceof File) {
      const url = URL.createObjectURL(file);
      setLocalPdfUrl(url);
      return () => URL.revokeObjectURL(url);
    } else {
      setLocalPdfUrl(null);
    }
  }, [file]);

  // ── Data fetching ───────────────────────────────────────────────────────────

  const fetchReports = async () => {
    try {
      const res = await axios.get(`${API_BASE}/reports`);
      if (res.data.success) setReportsList(res.data.reports);
    } catch (err) {
      console.error('Failed to fetch reports', err);
    }
  };

  useEffect(() => { fetchReports(); }, []);

  const loadReport = async (id) => {
    try {
      setLoading(true);
      setError(null);
      const res = await axios.get(`${API_BASE}/reports/${id}`);
      if (res.data.success) {
        const r = res.data.report;
        setStats(r.stats);
        setAnnotations(r.annotations);
        const url = r.pdf_url ? (r.pdf_url.startsWith('/api') ? r.pdf_url : `/api${r.pdf_url}`) : null;
        setHighlightedPdfUrl(url);
        setMarkdownText(r.markdown || '');
        setFile({ name: r.filename, size: 0 });
        setSelectedReportId(id);
        setMainTab('review');
        setActiveTab('text');
      }
    } catch (err) {
      setError('Failed to load the selected report.');
    } finally {
      setLoading(false);
    }
  };

  const startNewUpload = () => {
    setFile(null); setStats(null); setAnnotations(null);
    setHighlightedPdfUrl(null); setSelectedReportId(null);
    setError(null); setMarkdownText('');
    setMainTab('configure');
  };

  // ── Upload & Dropzone ───────────────────────────────────────────────────────

  const onDrop = useCallback((acceptedFiles) => {
    const f = acceptedFiles[0];
    if (f && f.type === 'application/pdf') {
      startNewUpload();
      setFile(f);
      setMainTab('configure');
    } else {
      setError('Please upload a valid PDF file.');
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    multiple: false,
    noClick: true,
  });

  // Handle paste functionality
  useEffect(() => {
    const handlePaste = (e) => {
      const pasteFile = e.clipboardData?.files?.[0];
      if (pasteFile && pasteFile.type === 'application/pdf') {
        startNewUpload();
        setFile(pasteFile);
        setMainTab('configure');
      }
    };
    window.addEventListener('paste', handlePaste);
    return () => window.removeEventListener('paste', handlePaste);
  }, []);

  const handleUrlInput = () => {
    const url = window.prompt("Enter Document URL:");
    if (url) {
      alert("URL processing backend endpoint configuration required. Please use file upload for now.");
    }
  };

  // ── Process ─────────────────────────────────────────────────────────────────

  const handleProcess = async () => {
    if (!file || file.size === 0) return;
    setLoading(true);
    setError(null);
    setStats(null);

    const formData = new FormData();
    formData.append('file', file);

    // Add Configuration Options
    formData.append('table_format', config.tableFormat);
    formData.append('confidence_level', config.confidenceLevel);
    formData.append('extract_header', config.extractHeader);
    formData.append('extract_footer', config.extractFooter);

    try {
      const response = await axios.post(`${API_BASE}/process`, formData, { timeout: 600000 });
      const data = response.data;
      if (!data.success) {
        setError(data.error || 'Processing failed on the server.');
        return;
      }
      setStats(data.stats);
      setAnnotations(data.annotations);
      const url = data.pdf_url ? (data.pdf_url.startsWith('/api') ? data.pdf_url : `/api${data.pdf_url}`) : null;
      setHighlightedPdfUrl(url);
      setMarkdownText(data.markdown || '');
      setSelectedReportId(data.id);
      setMainTab('review');
      setActiveTab('text');
      fetchReports();
    } catch (err) {
      setError('An error occurred while processing.');
    } finally {
      setLoading(false);
    }
  };

  const fileInfo = getFileStats(file, stats);

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-icon">M</div>
          <span>Mistral OCR</span>
        </div>

        <nav className="sidebar-nav">
          <div className="sidebar-section-title">Saved Reports</div>
          <div className="px-2 space-y-1">
            {reportsList.map(report => (
              <div
                key={report._id}
                onClick={() => loadReport(report._id)}
                className={`report-item ${selectedReportId === report._id ? 'report-item--active' : ''}`}
              >
                <div className="report-name">{report.filename}</div>
                <div className="report-meta">
                  <span>{new Date(report.created_at).toLocaleDateString()}</span>
                  <span>•</span>
                  <span>{report.stats?.pages || '?'} pgs</span>
                </div>
              </div>
            ))}
            {reportsList.length === 0 && <div className="p-3 text-xs text-muted italic">No reports yet</div>}
          </div>
        </nav>
      </aside>

      {/* ── Main Area ── */}
      <main className="main-area">
        {/* Header */}
        <header className="main-header">
          <div className="breadcrumb">
            <span>Document Intelligence</span>
            {file && (
              <div className="header-tabs">
                <button
                  className={`header-tab-btn ${mainTab === 'configure' ? 'header-tab-btn--active' : ''}`}
                  onClick={() => setMainTab('configure')}
                >
                  Configure
                </button>
                <button
                  className={`header-tab-btn ${mainTab === 'review' ? 'header-tab-btn--active' : ''}`}
                  onClick={() => setMainTab('review')}
                  disabled={!selectedReportId}
                >
                  Review
                </button>
              </div>
            )}
          </div>

          <div className="header-actions">
            {!file ? (
              <button className="btn-doc-ai" onClick={() => window.open('https://docs.mistral.ai', '_blank')}>
                <ExternalLink size={16} className="text-muted" /> Document AI docs
              </button>
            ) : (
              <>
                <button className="btn btn-ghost" onClick={startNewUpload}>
                  <Plus size={16} /> Add files
                </button>
                <button className="btn btn-ghost">
                  <Code size={16} /> Code
                </button>
                <button className="btn btn-ghost" onClick={startNewUpload}>
                  <RotateCcw size={16} /> Start over
                </button>
                <button
                  className="btn btn-run"
                  onClick={handleProcess}
                  disabled={loading || !file}
                >
                  {loading ? <Loader2 size={16} className="animate-spin" /> : null}
                  {!loading && selectedReportId ? <Download size={16} /> : null}
                  {loading ? 'Running...' : (selectedReportId ? 'Download' : 'Run')}
                </button>
              </>
            )}
          </div>
        </header>

        {/* Content Area */}
        <div className="content-grid-wrapper" {...getRootProps()}>
          <input {...getInputProps()} />
          {!file ? (
            <div className="empty-state">
              {isDragActive && (
                <div className="abs-fill bg-white bg-opacity-90 flex-col-center z-50">
                  <Upload size={48} className="text-primary animate-bounce text-mistral-orange" />
                  <h2 className="text-2xl font-bold mt-4">Drop PDF to process</h2>
                </div>
              )}
              <div className="es-icons">
                <div className="es-icon-card es-blue"><FileText size={28} /></div>
                <div className="es-icon-card es-red"><ScanText size={36} /></div>
                <div className="es-icon-card es-cyan"><ImageIcon size={28} /></div>
              </div>
              <h1 className="es-title">Extract text from your documents</h1>
              <p className="es-subtitle">10 Docs Max • 50MB Each • PDFs, Images & more</p>

              <div className="es-actions">
                <button className="es-btn es-btn-orange" onClick={open}>
                  Upload files
                </button>
                <button className="es-btn es-btn-gray" onClick={handleUrlInput}>
                  <LinkIcon size={14} /> Add a URL
                </button>
                <button className="es-btn es-btn-gray" onClick={() => alert("Press Ctrl+V or Cmd+V anywhere to paste a file.")}>
                  Paste files <span className="kbd">Ctrl+V</span>
                </button>
              </div>

              <p className="text-xs text-gray-400 mt-2 mb-10 pb-8">or drag and drop files here</p>

              <div className="es-footer-link">
                Need More? <a href="#">Try the API</a> . Up to 1,000 pages per document and 2,000 pages/min.
              </div>
            </div>
          ) : (
            <div className="content-grid">
              {/* Left: Always PDF Viewer container */}
              <div className="viewer-pane-left">
                <div className="pane-header">
                  <div className="pane-title">
                    <FileText size={16} className="text-error" />
                    <span title={file.name}>{file.name}</span>
                  </div>
                  <div className="pane-stats">
                    {mainTab === 'review' && stats ? (
                      <>
                        <div className="stat-item text-purple"><Clock size={12} /> {fileInfo.time}</div>
                        <div className="stat-item text-blue"><FileText size={12} /> {fileInfo.pages}</div>
                        <div className="stat-item text-orange"><Zap size={12} /> {fileInfo.cost}</div>
                        <div className="stat-item text-green"><PlusCircle size={12} /> {fileInfo.size}</div>
                      </>
                    ) : (
                      <div className="stat-pill-upload">
                        <Upload size={14} /> Uploaded
                      </div>
                    )}
                  </div>
                </div>
                <div className="pdf-canvas-container" style={{ background: '#525659', overflow: 'hidden' }}>
                  {loading ? (
                    <div className="flex-col-center h-full w-full justify-center text-white">
                      <Loader2 size={40} className="animate-spin text-mistral-orange mb-4" />
                      <p className="font-medium">Processing Document AI...</p>
                    </div>
                  ) : (
                    <PdfAnnotationViewer
                      pdfUrl={localPdfUrl || highlightedPdfUrl || null}
                      annotations={annotations}
                      showAnnotations={!!annotations}
                    />
                  )}
                </div>
              </div>

              {/* Right: Configure or Result Content */}
              <div className="viewer-pane-right">
                {mainTab === 'configure' ? (
                  <div className="rc-pane">
                    <div className="rc-block">
                      <div className="rc-label">
                        Model <AlertCircle size={14} className="text-muted" />
                      </div>
                      <div className="rc-box rc-row cursor-not-allowed bg-gray-50 flex justify-between items-center" style={{ padding: '12px 16px', background: '#f8f9fa' }}>
                        <div>
                          <div className="text-sm font-bold" style={{ fontSize: '0.85rem' }}>Mistral OCR Latest</div>
                          <div className="text-xs text-muted" style={{ fontSize: '0.75rem' }}>mistral-ocr-latest</div>
                        </div>
                        <ChevronDown size={16} className="text-muted" />
                      </div>
                    </div>

                    <div className="rc-block">
                      <div className="rc-label justify-between">
                        <div className="flex bg-transparent items-center gap-1">OCR Settings <AlertCircle size={14} className="text-muted" /></div>
                        <button className="text-muted hover:text-black transition-colors"><RotateCcw size={14} /></button>
                      </div>
                      <div className="rc-box">
                        <div className="rc-row">
                          <div className="rc-row-title">Table Extraction</div>
                          <div className="tab-group flex gap-2">
                            {['null', 'html', 'markdown'].map(opt => (
                              <button
                                key={opt}
                                onClick={() => setConfig(c => ({ ...c, tableFormat: opt }))}
                                className={`tab-btn ${config.tableFormat === opt ? 'tab-btn--active' : ''}`}
                              >
                                {opt === 'null' ? 'Inline' : opt.toUpperCase()}
                              </button>
                            ))}
                          </div>
                        </div>
                        <div className="rc-row">
                          <div className="rc-row-title">Confidence Granularity</div>
                          <select
                            className="w-full text-sm border-gray-200 rounded p-2"
                            value={config.confidenceLevel}
                            onChange={(e) => setConfig(c => ({ ...c, confidenceLevel: e.target.value }))}
                            style={{ border: '1px solid #e5e7eb', width: '100%', fontSize: '0.8rem', padding: '8px' }}
                          >
                            <option value="null">None (Fastest)</option>
                            <option value="page">Per Page (Recommended)</option>
                            <option value="word">Per Word (High Precision)</option>
                          </select>
                        </div>
                        <div className="rc-row" style={{ background: '#fcfcfd' }}>
                          <label className="flex items-center gap-2 cursor-pointer mb-3">
                            <input type="checkbox" checked={config.extractHeader} onChange={e => setConfig(c => ({ ...c, extractHeader: e.target.checked }))} style={{ accentColor: 'var(--mistral-orange)' }} />
                            <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>Extract Headers</span>
                          </label>
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input type="checkbox" checked={config.extractFooter} onChange={e => setConfig(c => ({ ...c, extractFooter: e.target.checked }))} style={{ accentColor: 'var(--mistral-orange)' }} />
                            <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>Extract Footers</span>
                          </label>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col h-full w-full overflow-hidden">
                    <div className="result-tabs">
                      <button
                        className={`result-tab-btn ${activeTab === 'text' ? 'result-tab-btn--active' : ''}`}
                        onClick={() => setActiveTab('text')}
                      >
                        Text Output
                      </button>
                      <button
                        className={`result-tab-btn ${activeTab === 'visual' ? 'result-tab-btn--active' : ''}`}
                        onClick={() => setActiveTab('visual')}
                      >
                        Visual
                      </button>
                      <button
                        className={`result-tab-btn ${activeTab === 'markdown' ? 'result-tab-btn--active' : ''}`}
                        onClick={() => setActiveTab('markdown')}
                      >
                        Markdown
                      </button>
                      <button
                        className={`result-tab-btn ${activeTab === 'json' ? 'result-tab-btn--active' : ''}`}
                        onClick={() => setActiveTab('json')}
                      >
                        JSON
                      </button>
                      <div className="flex-1" />
                      <button className="p-2 hover:bg-border-subtle rounded text-muted"><RotateCcw size={14} /></button>
                    </div>

                    <div className="result-content">
                      {activeTab === 'text' && (
                        <>
                          {stats?.pages && (
                            <div className="flex items-center justify-between mb-4 border-b pb-2">
                              <div className="text-xs text-muted font-medium">Page 1 of {stats?.pages}</div>
                              <button className="btn btn-secondary text-xs flex items-center gap-1 px-2 py-1"><Code size={12} /> Copy</button>
                            </div>
                          )}
                          <div className="markdown-view whitespace-pre-wrap">{markdownText.replace(/!\[.*?\]\(.*?\)/g, '') || 'No text extracted yet.'}</div>
                        </>
                      )}
                      {activeTab === 'markdown' && (
                        <pre className="text-xs text-gray-800 font-mono whitespace-pre-wrap">
                          {markdownText || 'No markdown yet.'}
                        </pre>
                      )}
                      {activeTab === 'json' && (
                        <div className="overflow-auto h-full p-4">
                          <pre className="text-xs text-gray-800 font-mono whitespace-pre-wrap">
                            {annotations ? JSON.stringify(annotations, null, 2) : 'No JSON data available.'}
                          </pre>
                        </div>
                      )}
                      {activeTab === 'visual' && (
                        <div className="visual-view-container" style={{ overflow: 'auto', height: '100%' }}>
                          {!annotations?.pages ? (
                            <div style={{ padding: 32, textAlign: 'center', color: '#9ca3af', fontSize: 13 }}>
                              No visual output available. Process a document first.
                            </div>
                          ) : (
                            annotations.pages.map((page, pageIdx) => {
                              // Build a fast image-id → image-object lookup for this page
                              const imageMap = {};
                              (page.images || []).forEach(img => { imageMap[img.id] = img; });

                              // Parse this page's markdown line-by-line
                              const lines = (page.markdown || '').split('\n');
                              const elements = [];
                              let textBuffer = [];

                              const flushText = (key) => {
                                const text = textBuffer.join('\n').trim();
                                if (text) {
                                  // Strip markdown syntax for clean reading
                                  const clean = text
                                    .replace(/^#{1,6}\s+/gm, '')
                                    .replace(/\*\*(.*?)\*\*/g, '$1')
                                    .replace(/__(.*?)__/g, '$1')
                                    .replace(/\*(.*?)\*/g, '$1');
                                  elements.push(
                                    <p key={`text-${key}`} style={{
                                      fontSize: 13, lineHeight: 1.75, color: '#374151',
                                      marginBottom: 6, whiteSpace: 'pre-wrap', fontFamily: 'inherit'
                                    }}>
                                      {clean}
                                    </p>
                                  );
                                }
                                textBuffer = [];
                              };

                              lines.forEach((line, lineIdx) => {
                                const imgMatch = line.match(/!\[.*?\]\((.*?)\)/);
                                if (imgMatch) {
                                  flushText(`${pageIdx}-${lineIdx}`);
                                  const imgId = imgMatch[1];
                                  const imgMeta = imageMap[imgId];

                                  // Use the file URL saved to disk by the backend (reliable,
                                  // avoids base64 data URL encoding/MIME issues)
                                  const rawUrl = imgMeta?.image_url;
                                  const imgSrc = rawUrl
                                    ? (rawUrl.startsWith('/api') ? rawUrl : `/api${rawUrl}`)
                                    : null;

                                  // Bounding box metadata (flat SDK fields)
                                  const tlx = imgMeta?.top_left_x     ?? 0;
                                  const tly = imgMeta?.top_left_y     ?? 0;
                                  const brx = imgMeta?.bottom_right_x ?? 0;
                                  const bry = imgMeta?.bottom_right_y ?? 0;
                                  const iw  = brx - tlx;
                                  const ih  = bry - tly;

                                  elements.push(
                                    <div key={`img-${pageIdx}-${lineIdx}`} style={{
                                      border: '1px solid #e5e7eb', borderRadius: 10,
                                      overflow: 'hidden', marginBottom: 14, marginTop: 6,
                                      background: '#fff', boxShadow: '0 1px 4px rgba(0,0,0,0.06)'
                                    }}>
                                      {/* Image header: name + dimensions */}
                                      <div style={{
                                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                        padding: '7px 12px', background: '#f9fafb',
                                        borderBottom: '1px solid #e5e7eb'
                                      }}>
                                        <span style={{ fontSize: 11, fontWeight: 700, fontFamily: 'monospace', color: '#374151' }}>
                                          {imgId}
                                        </span>
                                        <div style={{ display: 'flex', gap: 14, fontSize: 11, color: '#6b7280' }}>
                                          {(tlx > 0 || tly > 0) && (
                                            <span>x: {tlx}, y: {tly}</span>
                                          )}
                                          {(iw > 0 && ih > 0) && (
                                            <span>{iw} × {ih}</span>
                                          )}
                                        </div>
                                      </div>

                                      {/* Actual image */}
                                      <div style={{
                                        padding: '12px 16px', display: 'flex',
                                        justifyContent: 'center', alignItems: 'center',
                                        background: '#fff', minHeight: 48
                                      }}>
                                        {imgSrc ? (
                                          <img
                                            src={imgSrc}
                                            alt={imgId}
                                            style={{ maxWidth: '100%', maxHeight: 320, objectFit: 'contain', borderRadius: 6 }}
                                          />
                                        ) : (
                                          <span style={{ fontSize: 12, color: '#9ca3af', fontStyle: 'italic' }}>
                                            Image preview unavailable
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  );
                                } else {
                                  textBuffer.push(line);
                                }
                              });
                              flushText(`${pageIdx}-end`);

                              return (
                                <div key={pageIdx} style={{
                                  marginBottom: 32,
                                  paddingBottom: 28,
                                  borderBottom: pageIdx < annotations.pages.length - 1 ? '2px dashed #e5e7eb' : 'none'
                                }}>
                                  {/* Page header bar */}
                                  <div style={{
                                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                    marginBottom: 14, paddingBottom: 8, borderBottom: '1px solid #e5e7eb'
                                  }}>
                                    <span style={{
                                      fontSize: 11, fontWeight: 600, color: '#6b7280',
                                      textTransform: 'uppercase', letterSpacing: '0.06em'
                                    }}>
                                      Page {pageIdx + 1} of {annotations.pages.length}
                                    </span>
                                    <button
                                      style={{
                                        fontSize: 11, color: '#6b7280', background: 'none',
                                        border: '1px solid #e5e7eb', borderRadius: 5,
                                        padding: '3px 10px', cursor: 'pointer',
                                        display: 'flex', alignItems: 'center', gap: 4
                                      }}
                                      onClick={() => navigator.clipboard.writeText(page.markdown || '')}
                                    >
                                      <Copy size={10} /> Copy
                                    </button>
                                  </div>
                                  {/* Interleaved text + image content */}
                                  {elements}
                                </div>
                              );
                            })
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
