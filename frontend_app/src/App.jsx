import React, { useState, useCallback, useEffect, useRef } from 'react';
import axios from 'axios';
import { useDropzone } from 'react-dropzone';
import {
  Upload,
  FileText,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ChevronRight,
  Eye,
  Download,
  Clock,
  Menu,
  Plus,
  ScanText,
  FileCog,
  DatabaseZap,
  FileOutput,
  Table2,
  AlignLeft,
  ChevronDown,
  ChevronUp,
  ImageIcon,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const API_BASE = '/api';

// ── Processing Steps Config ───────────────────────────────────────────────────
const STEPS = [
  { key: 'uploading', label: 'Uploading PDF',         icon: Upload,      est: '2–5s' },
  { key: 'ocr',       label: 'Running Mistral OCR',   icon: ScanText,    est: '20–120s' },
  { key: 'pdf',       label: 'Generating PDF report', icon: FileOutput,  est: '3–10s' },
  { key: 'saving',    label: 'Saving to database',    icon: DatabaseZap, est: '1–2s' },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function useProcessingSteps(loading) {
  const [stepIdx, setStepIdx] = useState(0);
  const timerRef = useRef(null);

  useEffect(() => {
    if (loading) {
      setStepIdx(0);
      // Advance steps on realistic timers: 3s → 8s → 5s → hold
      const delays = [3000, 30000, 8000];
      let current = 0;
      const advance = () => {
        current++;
        if (current < STEPS.length) {
          setStepIdx(current);
          if (current < delays.length) {
            timerRef.current = setTimeout(advance, delays[current]);
          }
        }
      };
      timerRef.current = setTimeout(advance, delays[0]);
    } else {
      setStepIdx(0);
      clearTimeout(timerRef.current);
    }
    return () => clearTimeout(timerRef.current);
  }, [loading]);

  return stepIdx;
}

// ── Sub-Components ─────────────────────────────────────────────────────────────

function ProcessingOverlay({ stepIdx }) {
  return (
    <motion.div
      key="loading"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="abs-fill flex-col-center bg-blur z-10"
    >
      {/* Spinner */}
      <div className="spinner-wrap">
        <div className="spinner-ring"></div>
        <div className="spinner-inner">
          <Loader2 className="animate-pulse text-primary" size={22} />
        </div>
      </div>

      {/* Step list */}
      <div className="steps-list">
        {STEPS.map((step, i) => {
          const Icon = step.icon;
          const done    = i < stepIdx;
          const active  = i === stepIdx;
          const pending = i > stepIdx;
          return (
            <div key={step.key} className={`step-row ${active ? 'active' : done ? 'done' : 'pending'}`}>
              <div className="step-icon-wrap">
                {done
                  ? <CheckCircle2 size={16} />
                  : active
                  ? <Loader2 size={16} className="animate-spin" />
                  : <Icon size={16} />}
              </div>
              <div className="step-body">
                <span className="step-label">{step.label}</span>
                {active && <span className="step-est">~{step.est}</span>}
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-2 text-xs text-muted">Please keep this tab open…</p>
    </motion.div>
  );
}

function PageStatsTable({ pages }) {
  const [expanded, setExpanded] = useState(false);
  if (!pages || pages.length === 0) return null;

  const display = expanded ? pages : pages.slice(0, 8);

  return (
    <div className="page-stats-wrap">
      <button className="page-stats-header" onClick={() => setExpanded(e => !e)}>
        <Table2 size={14} />
        <span>Per-Page OCR Stats ({pages.length} pages)</span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      {expanded && (
        <div className="page-stats-table-wrap">
          <table className="page-stats-table">
            <thead>
              <tr>
                <th>Page</th>
                <th>Chars</th>
                <th>Images</th>
                <th>Tables</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {display.map((p, i) => {
                const md = p.markdown || '';
                const realText = md.replace(/!\[.*?\]\(.*?\)/g, '').trim();
                const imgCount = (p.images || []).length;
                const tblCount = (p.tables || []).length;
                const status = realText.length > 10 ? '✓' : imgCount > 0 ? '⚠' : '✗';
                const statusClass = status === '✓' ? 'ok' : status === '⚠' ? 'warn' : 'bad';
                return (
                  <tr key={i}>
                    <td>{i + 1}</td>
                    <td>{md.length}</td>
                    <td>{imgCount}</td>
                    <td>{tblCount}</td>
                    <td><span className={`badge badge-${statusClass}`}>{
                      status === '✓' ? 'Text' : status === '⚠' ? 'Image' : 'Empty'
                    }</span></td>
                  </tr>
                );
              })}
              {!expanded && pages.length > 8 && (
                <tr>
                  <td colSpan={5} className="text-center text-muted text-xs py-1">
                    + {pages.length - 8} more…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Image Annotations Panel ──────────────────────────────────────────────────
// Displays the bbox_annotation results — one card per detected image region.
// Each card shows image_type, short_description, and summary from ImageAnnotation.

function ImageAnnotationsPanel({ pages }) {
  const [expanded, setExpanded] = useState(false);

  // Collect all images that have a bbox annotation attached
  const annotatedImages = (pages || []).flatMap((page, pageIdx) =>
    (page.images || []).filter(img => img.bbox_annotation).map(img => ({
      pageNumber:       pageIdx + 1,
      imageType:        img.bbox_annotation?.image_type        || 'unknown',
      shortDescription: img.bbox_annotation?.short_description || '',
      summary:          img.bbox_annotation?.summary           || '',
    }))
  );

  if (annotatedImages.length === 0) return null;

  const displayed = expanded ? annotatedImages : annotatedImages.slice(0, 3);

  // Badge colour per image type
  const typeColor = { graph: 'primary', table: 'ok', text: 'warn', image: 'muted', unknown: 'muted' };

  return (
    <div className="page-stats-wrap">
      <button className="page-stats-header" onClick={() => setExpanded(e => !e)}>
        <ImageIcon size={14} />
        <span>Image Annotations ({annotatedImages.length} detected)</span>
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {expanded && (
        <div className="img-annotation-list">
          {displayed.map((img, i) => (
            <div key={i} className="img-annotation-card">
              <div className="img-annotation-header">
                <span className={`badge badge-${typeColor[img.imageType] || 'muted'}`}>
                  {img.imageType}
                </span>
                <span className="img-annotation-page">Page {img.pageNumber}</span>
              </div>
              {img.shortDescription && (
                <p className="img-annotation-desc">{img.shortDescription}</p>
              )}
              {img.summary && (
                <p className="img-annotation-summary">{img.summary}</p>
              )}
            </div>
          ))}
          {!expanded && annotatedImages.length > 3 && (
            <p className="text-center text-muted text-xs py-1">
              + {annotatedImages.length - 3} more…
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────

function App() {
  const [file, setFile]                     = useState(null);
  const [loading, setLoading]               = useState(false);
  const [error, setError]                   = useState(null);
  const [highlightedPdfUrl, setHighlightedPdfUrl] = useState(null);
  const [annotations, setAnnotations]       = useState(null);
  const [stats, setStats]                   = useState(null);
  const [markdownText, setMarkdownText]     = useState('');
  const [activeTab, setActiveTab]           = useState('preview');

  const [reportsList, setReportsList]       = useState([]);
  const [selectedReportId, setSelectedReportId] = useState(null);

  const stepIdx = useProcessingSteps(loading);

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
        // Old reports stored url as /outputs/... — prefix /api for proxy
        const url = r.pdf_url.startsWith('/api') ? r.pdf_url : `/api${r.pdf_url}`;
        setHighlightedPdfUrl(url);
        setMarkdownText(r.markdown || '');
        setFile({ name: r.filename, size: 0 });
        setSelectedReportId(id);
        setActiveTab('preview');
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
  };

  // ── Upload & Dropzone ───────────────────────────────────────────────────────

  const onDrop = useCallback((acceptedFiles) => {
    const f = acceptedFiles[0];
    if (f && f.type === 'application/pdf') {
      startNewUpload();
      setFile(f);
    } else {
      setError('Please upload a valid PDF file.');
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    multiple: false,
  });

  // ── Process ─────────────────────────────────────────────────────────────────

  const handleProcess = async () => {
    if (!file || file.size === 0) return;
    setLoading(true);
    setError(null);
    setStats(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await axios.post(`${API_BASE}/process`, formData, {
        timeout: 600000,   // 10 minutes — large docs take time
      });
      const data = response.data;

      if (!data.success) {
        setError(data.error || 'Processing failed on the server.');
        return;
      }

      setStats(data.stats);
      setAnnotations(data.annotations);
      // Backend stores /outputs/... → prefix /api for Vite proxy
      const url = data.pdf_url.startsWith('/api') ? data.pdf_url : `/api${data.pdf_url}`;
      setHighlightedPdfUrl(url);
      setMarkdownText(data.markdown || '');
      setSelectedReportId(data.id);
      setActiveTab('preview');
      fetchReports();
    } catch (err) {
      console.error('Processing error:', err);
      if (err.code === 'ECONNABORTED') {
        setError('Request timed out. The document may be very large — try again or check the terminal.');
      } else {
        setError('An error occurred while processing. Check the backend terminal for details.');
      }
    } finally {
      setLoading(false);
    }
  };

  // ── Computed ─────────────────────────────────────────────────────────────────

  const pagesData = annotations?.pages || [];

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <Menu size={22} className="text-primary" />
          <span className="gradient-text logo-text">Mistral OCR</span>
        </div>

        <div className="sidebar-body">
          <button
            onClick={startNewUpload}
            className={`new-btn ${!selectedReportId ? 'new-btn--active' : ''}`}
          >
            <div className="new-btn-icon"><Plus size={16} /></div>
            <span>New Process</span>
          </button>

          <h3 className="sidebar-section-title">Saved Reports</h3>

          {reportsList.length === 0 ? (
            <p className="sidebar-empty">No reports yet.</p>
          ) : (
            reportsList.map(report => (
              <button
                key={report._id}
                onClick={() => loadReport(report._id)}
                className={`report-item ${selectedReportId === report._id ? 'report-item--active' : ''}`}
              >
                <FileText size={16} className="shrink-0 mt-px" />
                <div className="report-item-body">
                  <p className="report-name">{report.filename}</p>
                  <div className="report-meta">
                    <span><Clock size={10} /> {new Date(report.created_at).toLocaleDateString()}</span>
                    <span>•</span>
                    <span>{report.stats?.pages ?? '?'} pgs</span>
                    {report.stats?.empty_pages > 0 && (
                      <span className="warn-badge">{report.stats.empty_pages} empty</span>
                    )}
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="main-area">
        {/* Header */}
        <header className="main-header">
          <div>
            <h2 className="main-title">{selectedReportId ? 'Analysis Report' : 'Upload Document'}</h2>
            <p className="main-subtitle">High-precision Mistral OCR document intelligence</p>
          </div>
          <div className="api-badge">
            <CheckCircle2 size={14} className="text-success" /> API Online
          </div>
        </header>

        <div className="content-grid">
          {/* Left column: upload + stats */}
          <div className="left-col">
            <section className="card glass">
              {!selectedReportId ? (
                <>
                  <div
                    {...getRootProps()}
                    className={`dropzone ${isDragActive ? 'dropzone--active' : ''} ${file && file.size > 0 ? 'dropzone--filled' : ''}`}
                  >
                    <input {...getInputProps()} />
                    <div className={`drop-icon ${isDragActive ? 'animate-pulse' : ''}`}>
                      <FileText size={30} className={isDragActive ? 'text-primary' : 'text-muted'} />
                    </div>
                    {file && file.size > 0 ? (
                      <div className="text-center">
                        <p className="file-name">{file.name}</p>
                        <p className="file-size">{(file.size / 1024).toFixed(1)} KB</p>
                      </div>
                    ) : (
                      <>
                        <p className="drop-label">Drag &amp; drop your PDF here</p>
                        <p className="drop-sub">or click to browse</p>
                      </>
                    )}
                  </div>

                  <button
                    onClick={handleProcess}
                    disabled={!file || file.size === 0 || loading}
                    className="btn btn-primary w-full mt-5 justify-center"
                    id="btn-process"
                  >
                    {loading ? (
                      <><Loader2 className="animate-spin" size={18} /> Processing…</>
                    ) : (
                      <>Process with AI <ChevronRight size={18} /></>
                    )}
                  </button>
                </>
              ) : (
                <div className="loaded-state">
                  <div className="loaded-icon">
                    <CheckCircle2 size={30} className="text-success" />
                  </div>
                  <h3 className="loaded-title">Report Loaded</h3>
                  <p className="loaded-name">{file?.name}</p>
                  <button onClick={startNewUpload} className="btn btn-secondary w-full justify-center mt-4">
                    Analyze New Document
                  </button>
                </div>
              )}

              <AnimatePresence>
                {error && (
                  <motion.div
                    initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                    className="error-banner"
                  >
                    <AlertCircle size={15} className="shrink-0 mt-px" />
                    <span>{error}</span>
                  </motion.div>
                )}
              </AnimatePresence>
            </section>

            {/* Stats card */}
            <AnimatePresence>
              {stats && (
                <motion.section
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="card glass stats-card"
                >
                  <h3 className="stats-heading">
                    <CheckCircle2 size={13} /> Processing Stats
                  </h3>
                  <div className="stats-grid">
                    <div className="stat-box">
                      <p className="stat-label">Total Pages</p>
                      <p className="stat-value">{stats.pages}</p>
                    </div>
                    <div className="stat-box">
                      <p className="stat-label">Time Taken</p>
                      <p className="stat-value">{stats.time_taken}s</p>
                    </div>
                    {stats.empty_pages > 0 && (
                      <div className="stat-box stat-box--warn">
                        <p className="stat-label">Empty Pages</p>
                        <p className="stat-value warn">{stats.empty_pages}</p>
                      </div>
                    )}
                    <div className="stat-box stat-box--primary">
                      <p className="stat-label">API Cost</p>
                      <p className="stat-value gradient-text">${stats.cost}</p>
                    </div>
                  </div>
                </motion.section>
              )}
            </AnimatePresence>
          </div>

          {/* Right column: viewer */}
          <div className="right-col">
            <section className="card glass viewer-card">
              {/* Tab bar */}
              <div className="tab-bar">
                <div className="tab-group">
                  {[
                    { key: 'preview',    Icon: Eye,       label: 'Visual Preview' },
                    { key: 'data',       Icon: FileCog,   label: 'Structured Data' },
                    { key: 'markdown',   Icon: AlignLeft, label: 'Raw Text' },
                  ].map(({ key, Icon, label }) => (
                    <button
                      key={key}
                      onClick={() => setActiveTab(key)}
                      className={`tab-btn ${activeTab === key ? 'tab-btn--active' : ''}`}
                    >
                      <Icon size={14} /> {label}
                    </button>
                  ))}
                </div>

                {highlightedPdfUrl && (
                  <a
                    href={highlightedPdfUrl}
                    download="OCR_Report.pdf"
                    className="btn btn-secondary py-1 px-3 text-xs"
                  >
                    <Download size={13} /> Download
                  </a>
                )}
              </div>

              {/* Viewer area */}
              <div className="viewer-area">
                <AnimatePresence mode="wait">

                  {/* Empty state */}
                  {!highlightedPdfUrl && !loading && (
                    <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      className="abs-fill flex-col-center text-muted text-center p-8"
                    >
                      <div className="empty-icon"><FileText size={38} /></div>
                      <p style={{ maxWidth: 260 }}>
                        Upload a document or select one from the sidebar to view its OCR analysis.
                      </p>
                    </motion.div>
                  )}

                  {/* Loading overlay with step tracker */}
                  {loading && <ProcessingOverlay stepIdx={stepIdx} />}

                  {/* PDF preview */}
                  {activeTab === 'preview' && highlightedPdfUrl && !loading && (
                    <motion.iframe
                      key={`pdf-${highlightedPdfUrl}`}
                      initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                      src={highlightedPdfUrl}
                      className="viewer-iframe"
                      title="OCR Result Preview"
                    />
                  )}

                  {/* Structured data */}
                  {activeTab === 'data' && !loading && (
                    <motion.div key="data" initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}
                      className="data-panel"
                    >
                      {annotations ? (
                        <div className="space-y-5">
                          {/* Top cards */}
                          <div className="info-grid">
                            <div className="info-box">
                              <h4 className="info-label">Language</h4>
                              <p className="info-val">{annotations.document_annotation?.language || 'N/A'}</p>
                            </div>
                            <div className="info-box">
                              <h4 className="info-label">Pages</h4>
                              <p className="info-val">{pagesData.length}</p>
                            </div>
                          </div>

                          {/* Summary */}
                          {annotations.document_annotation?.summary && (
                            <div className="info-box">
                              <h4 className="info-label">Document Summary</h4>
                              <p className="info-text">{annotations.document_annotation.summary}</p>
                            </div>
                          )}

                          {/* Authors */}
                          {annotations.document_annotation?.authors?.length > 0 && (
                            <div className="info-box">
                              <h4 className="info-label">Authors</h4>
                              <p className="info-text">{annotations.document_annotation.authors.join(', ')}</p>
                            </div>
                          )}

                          {/* Stamps / Handwriting */}
                          {annotations.document_annotation?.stamps_extract && (
                            <div className="info-box">
                              <h4 className="info-label">Stamps / Seals</h4>
                              <p className="info-text mono">{annotations.document_annotation.stamps_extract}</p>
                            </div>
                          )}
                          {annotations.document_annotation?.handwriting_extract && (
                            <div className="info-box">
                              <h4 className="info-label">Handwriting / Signatures</h4>
                              <p className="info-text mono">{annotations.document_annotation.handwriting_extract}</p>
                            </div>
                          )}

                          {/* Per-page stats */}
                          <PageStatsTable pages={pagesData} />

                          {/* BBox Image Annotations — short_description + summary per image */}
                          <ImageAnnotationsPanel pages={pagesData} />

                          {/* Raw JSON */}
                          <details>
                            <summary className="raw-summary">Raw JSON Metadata</summary>
                            <pre className="raw-json">{JSON.stringify(annotations, null, 2)}</pre>
                          </details>
                        </div>
                      ) : (
                        <div className="abs-fill flex-col-center text-muted">No data available.</div>
                      )}
                    </motion.div>
                  )}

                  {/* Raw markdown text */}
                  {activeTab === 'markdown' && !loading && (
                    <motion.div key="markdown" initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}
                      className="data-panel"
                    >
                      {markdownText ? (
                        <pre className="markdown-raw">{markdownText}</pre>
                      ) : (
                        <div className="abs-fill flex-col-center text-muted">No extracted text available.</div>
                      )}
                    </motion.div>
                  )}

                </AnimatePresence>
              </div>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
