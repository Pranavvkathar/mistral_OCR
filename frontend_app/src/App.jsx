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
  Layout,
  Play,
  FileJson,
  Code,
  RotateCcw,
  PlusCircle,
  Home,
  Layers,
  Zap,
  Mic,
  Settings,
  MoreVertical,
  Minus,
  Maximize2,
  RotateCw,
  Search,
  ExternalLink,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

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

// ── Components ─────────────────────────────────────────────────────────────

function NavbarItem({ icon: Icon, label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`sidebar-nav-item ${active ? 'sidebar-nav-item--active' : ''}`}
    >
      <Icon size={18} />
      <span>{label}</span>
    </button>
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
  const [activeTab, setActiveTab]           = useState('markdown'); 
  const [mainTab, setMainTab]               = useState('review');   

  const [reportsList, setReportsList]       = useState([]);
  const [selectedReportId, setSelectedReportId] = useState(null);

  // 📝 Advanced OCR Configuration State
  const [config, setConfig] = useState({
    tableFormat: 'null',           // 'null', 'html', 'markdown'
    confidenceLevel: 'null',      // 'null', 'page', 'word'
    extractHeader: false,
    extractFooter: false,
  });

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
        const url = r.pdf_url.startsWith('/api') ? r.pdf_url : `/api${r.pdf_url}`;
        setHighlightedPdfUrl(url);
        setMarkdownText(r.markdown || '');
        setFile({ name: r.filename, size: 0 }); 
        setSelectedReportId(id);
        setMainTab('review');
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
    setMainTab('review');
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
    noClick: !!file, 
  });

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
      const url = data.pdf_url.startsWith('/api') ? data.pdf_url : `/api${data.pdf_url}`;
      setHighlightedPdfUrl(url);
      setMarkdownText(data.markdown || '');
      setSelectedReportId(data.id);
      setMainTab('review'); 
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
          <span>AI Studio</span>
        </div>

        <nav className="sidebar-nav">
          <NavbarItem icon={Home} label="Home" />
          <NavbarItem icon={Zap} label="API Keys" />
          
          <div className="sidebar-section-title">Create</div>
          <NavbarItem icon={Play} label="Playground" />
          <NavbarItem icon={Layers} label="Agents" />
          <NavbarItem icon={DatabaseZap} label="Batches" />
          <NavbarItem icon={ScanText} label="Document AI" active />
          <NavbarItem icon={Zap} label="Workflows" />
          <NavbarItem icon={Mic} label="Audio" />

          <div className="sidebar-section-title">Context</div>
          <NavbarItem icon={FileText} label="Files" />
          
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
          </div>

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
            >
              Review
            </button>
          </div>

          <div className="header-actions">
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
              {loading ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
              {loading ? 'Running...' : (selectedReportId ? 'Download' : 'Run')}
            </button>
          </div>
        </header>

        {/* Sub Header for Stats */}
        {file && (
          <div className="document-sub-header">
            <div className="doc-title-row">
              <FileText size={16} className="text-error" />
              <span>{file.name}</span>
            </div>
            <div className="doc-stats">
              <div className="stat-chip"><Clock size={12} /> {fileInfo.time}</div>
              <div className="stat-chip"><FileText size={12} /> {fileInfo.pages}</div>
              <div className="stat-chip"><Zap size={12} /> {fileInfo.cost}</div>
              <div className="stat-chip"><PlusCircle size={12} /> {fileInfo.size}</div>
            </div>
          </div>
        )}

        <div className="content-grid" {...getRootProps()}>
          <input {...getInputProps()} />
          
          {/* Left: Configuration or PDF Viewer */}
          <div className="viewer-pane-left">
            {mainTab === 'configure' ? (
              <div className="config-panel">
                <div className="mb-1">
                  <h2 className="config-title">OCR Configuration</h2>
                  <p className="config-hint">Fine-tune the extraction settings for high-precision results.</p>
                </div>

                <div className="config-group">
                  <label className="config-label">Table Extraction Format</label>
                  <div className="config-btn-grid">
                    {['null', 'html', 'markdown'].map(opt => (
                      <button
                        key={opt}
                        onClick={() => setConfig(c => ({...c, tableFormat: opt}))}
                        className={`config-btn ${config.tableFormat === opt ? 'config-btn--active' : ''}`}
                      >
                        {opt === 'null' ? 'Inline' : opt.toUpperCase()}
                      </button>
                    ))}
                  </div>
                  <p className="config-hint">HTML format is recommended for complex financial tables.</p>
                </div>

                <div className="config-group">
                  <label className="config-label">AI Confidence Granularity</label>
                  <select 
                    className="config-select"
                    value={config.confidenceLevel}
                    onChange={(e) => setConfig(c => ({...c, confidenceLevel: e.target.value}))}
                  >
                    <option value="null">None (Fastest)</option>
                    <option value="page">Per Page (Recommended)</option>
                    <option value="word">Per Word (High Precision)</option>
                  </select>
                </div>

                <div className="config-group mt-8 pt-4" style={{borderTop: '1px solid var(--border)'}}>
                  <label className="config-toggle">
                    <input 
                      type="checkbox" 
                      checked={config.extractHeader}
                      onChange={(e) => setConfig(c => ({...c, extractHeader: e.target.checked}))}
                    />
                    <span>Extract Header Content</span>
                  </label>
                  <label className="config-toggle">
                    <input 
                      type="checkbox" 
                      checked={config.extractFooter}
                      onChange={(e) => setConfig(c => ({...c, extractFooter: e.target.checked}))}
                    />
                    <span>Extract Footer Content</span>
                  </label>
                </div>
              </div>
            ) : !file ? (
              <div className="abs-fill flex-col-center">
                <div className="p-8 border-2 border-dashed border-border rounded-xl flex-col-center bg-bg-subtle cursor-pointer hover:bg-white transition-colors">
                  <Upload size={48} className="text-muted mb-2" />
                  <h3 className="font-bold text-lg text-center">Extract text from your documents</h3>
                  <p className="text-muted text-sm text-center">10 Docs Max • 50MB Each • PDFs, Images & more</p>
                  <button className="btn btn-run mt-4 px-8">Upload files</button>
                  <p className="text-xs text-muted mt-2">or drag and drop files here</p>
                </div>
              </div>
            ) : (
              <div className="pdf-canvas-container">
                {loading ? (
                  <div className="flex-col-center">
                    <Loader2 size={40} className="animate-spin text-primary" />
                    <p className="mt-4 font-medium">Processing Document AI...</p>
                  </div>
                ) : (
                  <>
                    <iframe src={highlightedPdfUrl} className="viewer-iframe" />
                    <div className="pdf-navigator">
                      <button className="nav-btn"><Minus size={16}/></button>
                      <span>1 / {stats?.pages || 1}</span>
                      <button className="nav-btn"><Plus size={16}/></button>
                      <div className="w-px h-4 bg-gray-700 mx-2" />
                      <span>100%</span>
                      <div className="w-px h-4 bg-gray-700 mx-2" />
                      <button className="nav-btn"><RotateCw size={16}/></button>
                    </div>
                  </>
                )}
              </div>
            )}
            {isDragActive && (
              <div className="abs-fill bg-white bg-opacity-90 flex-col-center z-50">
                <Upload size={48} className="text-primary animate-bounce" />
                <h2 className="text-2xl font-bold">Drop PDF to process</h2>
              </div>
            )}
          </div>

          {/* Right: Result Area */}
          <div className="viewer-pane-right">
            <div className="result-tabs">
              <button
                className={`result-tab-btn ${activeTab === 'data' ? 'result-tab-btn--active' : ''}`}
                onClick={() => setActiveTab('data')}
              >
                Structured Output
              </button>
              <button
                className={`result-tab-btn ${activeTab === 'json' ? 'result-tab-btn--active' : ''}`}
                onClick={() => setActiveTab('json')}
              >
                JSON
              </button>
              <button
                className={`result-tab-btn ${activeTab === 'markdown' ? 'result-tab-btn--active' : ''}`}
                onClick={() => setActiveTab('markdown')}
              >
                Text
              </button>
              <div className="flex-1" />
              <button className="p-2 hover:bg-border-subtle rounded"><Search size={16}/></button>
              <button className="p-2 hover:bg-border-subtle rounded"><Download size={16}/></button>
            </div>

            <div className="result-content">
              {activeTab === 'markdown' && (
                <div className="markdown-view">{markdownText || 'No text extracted yet.'}</div>
              )}
              {activeTab === 'json' && (
                <pre className="text-xs text-gray-600">
                  {annotations ? JSON.stringify(annotations, null, 2) : 'No data yet.'}
                </pre>
              )}
              {activeTab === 'data' && (
                <div className="space-y-6">
                  {annotations ? (
                    <>
                      {/* Document Overview Data */}
                      <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px'}}>
                        <div className="info-box">
                          <div className="info-label">Language</div>
                          <div className="info-val">{annotations.document_annotation?.language || 'N/A'}</div>
                        </div>
                        <div className="info-box">
                          <div className="info-label">OCR Confidence</div>
                          <div className="info-val text-success">
                            {annotations.pages?.[0]?.confidence_scores 
                              ? (annotations.pages[0].confidence_scores.average_page_confidence_score * 100).toFixed(1) + '%'
                              : 'High'}
                          </div>
                        </div>
                      </div>

                      <div className="info-box">
                        <div className="info-label">Document Summary</div>
                        <div className="info-text">{annotations.document_annotation?.summary || 'N/A'}</div>
                      </div>

                      {/* Header/Footer Preview (if extracted) */}
                      {(annotations.pages?.[0]?.header || annotations.pages?.[0]?.footer) && (
                        <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                          {annotations.pages[0].header && (
                            <div className="p-3 bg-border-subtle rounded text-xs opacity-75">
                              <span className="font-bold text-primary mr-2 uppercase">Header:</span>
                              {annotations.pages[0].header}
                            </div>
                          )}
                          {annotations.pages[0].footer && (
                            <div className="p-3 bg-border-subtle rounded text-xs opacity-75">
                              <span className="font-bold text-primary mr-2 uppercase">Footer:</span>
                              {annotations.pages[0].footer}
                            </div>
                          )}
                        </div>
                      )}

                      {/* Per-Page Detail Table */}
                      <div className="data-table-wrap">
                        <table className="data-table">
                          <thead>
                            <tr>
                              <th>Page</th>
                              <th>Confidence</th>
                              <th>Images</th>
                              <th>Tables</th>
                            </tr>
                          </thead>
                          <tbody>
                            {annotations.pages?.map((pg, i) => (
                              <tr key={i}>
                                <td style={{fontWeight: 600}}>{i + 1}</td>
                                <td className="text-success">
                                  {pg.confidence_scores 
                                    ? (pg.confidence_scores.average_page_confidence_score * 100).toFixed(1) + '%'
                                    : '--'}
                                </td>
                                <td>{pg.images?.length || 0}</td>
                                <td>{pg.tables?.length || 0}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  ) : 'No data yet.'}
                </div>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
