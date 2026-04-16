/**
 * PdfAnnotationViewer.jsx
 * =======================
 * Renders a PDF using react-pdf (PDF.js canvas) and overlays
 * Mistral OCR bounding-box annotation boxes on each detected image region,
 * matching the behaviour seen in the official Mistral AI playground.
 *
 * Coordinate System
 * -----------------
 * Mistral returns bbox in a 0–1000 normalised space:
 *   top_left     : { x, y }   (origin = top-left corner of the page)
 *   bottom_right : { x, y }
 *
 * To convert to pixels on the rendered canvas:
 *   pixel_x = (bbox.top_left.x     / 1000) * renderedWidth
 *   pixel_y = (bbox.top_left.y     / 1000) * renderedHeight
 *   width   = ((bbox.bottom_right.x - bbox.top_left.x) / 1000) * renderedWidth
 *   height  = ((bbox.bottom_right.y - bbox.top_left.y) / 1000) * renderedHeight
 *
 * Props
 * -----
 *   pdfUrl        {string}   URL/object-URL of the PDF to render
 *   annotations   {object}   Full OCR result object (annotations.pages[n].images[])
 *   showAnnotations {bool}   Whether to show annotation overlays (default true)
 */

import React, { useState, useRef, useCallback } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

// ── PDF.js worker ──────────────────────────────────────────────────────────────
// react-pdf bundles its own PDF.js worker. Point to it so rendering works.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

// ── Colour palette for annotation boxes ────────────────────────────────────────
// Rotates through several accent colours so overlapping images are distinguishable
const ANNOTATION_COLORS = [
  { border: '#3b82f6', bg: 'rgba(59,130,246,0.08)', label: '#3b82f6' }, // blue
  { border: '#8b5cf6', bg: 'rgba(139,92,246,0.08)',  label: '#8b5cf6' }, // purple
  { border: '#10b981', bg: 'rgba(16,185,129,0.08)',  label: '#10b981' }, // green
  { border: '#f59e0b', bg: 'rgba(245,158,11,0.08)',  label: '#f59e0b' }, // amber
  { border: '#ef4444', bg: 'rgba(239,68,68,0.08)',   label: '#ef4444' }, // red
];

function getColor(index) {
  return ANNOTATION_COLORS[index % ANNOTATION_COLORS.length];
}

// ── AnnotationOverlay ──────────────────────────────────────────────────────────
// Renders the annotation boxes for ONE page on top of the rendered canvas.
//
// Coordinate System (confirmed from SDK source):
//   OCRImageObject has flat fields: top_left_x, top_left_y, bottom_right_x, bottom_right_y
//   These are pixel values within the internal page image Mistral rendered at `dimensions.dpi`.
//   The page's `dimensions.width` and `dimensions.height` give the full pixel space.
//   To map to the react-pdf canvas:
//     rendered_x = (top_left_x / dimensions.width)  * renderedPageWidth
//     rendered_y = (top_left_y / dimensions.height) * renderedPageHeight
function AnnotationOverlay({ images, pageWidth, pageHeight, pageDimensions }) {
  if (!images || images.length === 0) return null;

  // Use the actual page render dimensions from Mistral, fall back to 1000 if missing
  const srcW = pageDimensions?.width  || 1000;
  const srcH = pageDimensions?.height || 1000;

  return (
    <div
      style={{
        position: 'absolute',
        top: 0, left: 0,
        width: pageWidth,
        height: pageHeight,
        pointerEvents: 'none',
        zIndex: 10,
      }}
    >
      {images.map((img, idx) => {
        // Read flat coordinate fields directly from the OCRImageObject
        const tlx = img.top_left_x     ?? 0;
        const tly = img.top_left_y     ?? 0;
        const brx = img.bottom_right_x ?? 0;
        const bry = img.bottom_right_y ?? 0;

        // Skip images with no valid bounding box
        if (tlx === 0 && tly === 0 && brx === 0 && bry === 0) return null;

        // Scale from Mistral's internal pixel space → rendered canvas pixels
        const left   = (tlx / srcW) * pageWidth;
        const top    = (tly / srcH) * pageHeight;
        const width  = ((brx - tlx) / srcW) * pageWidth;
        const height = ((bry - tly) / srcH) * pageHeight;

        if (width < 4 || height < 4) return null;

        const color = getColor(idx);

        return (
          <div
            key={img.id || idx}
            style={{
              position: 'absolute',
              left,
              top,
              width,
              height,
              border: `2px solid ${color.border}`,
              background: color.bg,
              borderRadius: 3,
              boxSizing: 'border-box',
            }}
          >
            {/* Label chip — top-left corner, exactly like Mistral playground */}
            <div
              style={{
                position: 'absolute',
                top: -1,
                left: -1,
                background: color.border,
                color: '#fff',
                fontSize: 10,
                fontWeight: 700,
                fontFamily: 'monospace',
                padding: '1px 6px',
                borderRadius: '3px 0 3px 0',
                letterSpacing: '0.02em',
                whiteSpace: 'nowrap',
                lineHeight: '18px',
                maxWidth: Math.max(20, width - 4),
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {img.id || `img-${idx}`}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────────────────────
export default function PdfAnnotationViewer({
  pdfUrl,
  annotations,
  showAnnotations = true,
}) {
  const [numPages, setNumPages]       = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize]       = useState({ width: 0, height: 0 });
  const [docError, setDocError]       = useState(null);
  const containerRef                  = useRef(null);

  // Called by react-pdf once the document metadata is parsed
  const onDocumentLoadSuccess = useCallback(({ numPages: n }) => {
    setNumPages(n);
    setCurrentPage(1);
    setDocError(null);
  }, []);

  const onDocumentLoadError = useCallback((err) => {
    console.error('[PdfAnnotationViewer] load error:', err);
    setDocError(err?.message || 'Failed to load PDF.');
  }, []);

  // Called by react-pdf after each page renders — gives us the actual pixel dims
  const onPageRenderSuccess = useCallback((page) => {
    setPageSize({ width: page.width, height: page.height });
  }, []);

  // ── Annotation data for the current page ──────────────────────────────────
  // annotations.pages is 0-indexed; currentPage is 1-indexed
  const currentPageData = annotations?.pages?.[currentPage - 1] ?? null;
  const currentPageAnnotations = currentPageData?.images || [];
  // dimensions gives us the pixel space Mistral used (dpi, width, height)
  const currentPageDimensions  = currentPageData?.dimensions ?? null;

  // ── Navigation helpers ─────────────────────────────────────────────────────
  const goToPrev = () => setCurrentPage(p => Math.max(1, p - 1));
  const goToNext = () => setCurrentPage(p => Math.min(numPages || 1, p + 1));

  if (!pdfUrl) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#9ca3af', fontSize: 14 }}>
        No PDF loaded.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '100%', overflow: 'hidden' }}>

      {/* ── Scrollable PDF canvas area ── */}
      <div
        ref={containerRef}
        style={{
          flex: 1,
          overflow: 'auto',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          background: '#525659',
          padding: '16px 0',
        }}
      >
        {docError ? (
          <div style={{ color: '#f87171', fontSize: 13, padding: 24 }}>
            ⚠ {docError}
          </div>
        ) : (
          <Document
            file={pdfUrl}
            onLoadSuccess={onDocumentLoadSuccess}
            onLoadError={onDocumentLoadError}
            loading={
              <div style={{ color: '#fff', padding: 32, textAlign: 'center', fontSize: 14 }}>
                Loading PDF…
              </div>
            }
          >
            {/* Render only the current page for performance */}
            <div style={{ position: 'relative', display: 'inline-block', boxShadow: '0 4px 24px rgba(0,0,0,0.5)' }}>
              <Page
                pageNumber={currentPage}
                width={Math.min(containerRef.current?.clientWidth - 32 || 700, 820)}
                renderTextLayer={false}
                renderAnnotationLayer={false}
                onRenderSuccess={onPageRenderSuccess}
              />

              {/* Annotation overlay — only shown after OCR has run */}
              {showAnnotations && pageSize.width > 0 && (
                <AnnotationOverlay
                  images={currentPageAnnotations}
                  pageWidth={pageSize.width}
                  pageHeight={pageSize.height}
                  pageDimensions={currentPageDimensions}
                />
              )}
            </div>
          </Document>
        )}
      </div>

      {/* ── Page Navigation Bar ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          padding: '8px 16px',
          background: '#3c3d3f',
          borderTop: '1px solid #555',
          flexShrink: 0,
        }}
      >
        <button
          onClick={goToPrev}
          disabled={currentPage <= 1}
          style={{
            background: 'transparent',
            border: '1px solid #888',
            color: currentPage <= 1 ? '#555' : '#ccc',
            cursor: currentPage <= 1 ? 'not-allowed' : 'pointer',
            borderRadius: 4,
            padding: '3px 10px',
            fontSize: 16,
            lineHeight: 1,
          }}
        >
          ‹
        </button>

        <span style={{ color: '#ddd', fontSize: 13, minWidth: 80, textAlign: 'center' }}>
          {currentPage} / {numPages ?? '…'}
        </span>

        <button
          onClick={goToNext}
          disabled={!numPages || currentPage >= numPages}
          style={{
            background: 'transparent',
            border: '1px solid #888',
            color: (!numPages || currentPage >= numPages) ? '#555' : '#ccc',
            cursor: (!numPages || currentPage >= numPages) ? 'not-allowed' : 'pointer',
            borderRadius: 4,
            padding: '3px 10px',
            fontSize: 16,
            lineHeight: 1,
          }}
        >
          ›
        </button>

        <div style={{ width: 1, height: 16, background: '#555', margin: '0 4px' }} />
        <span style={{ color: '#aaa', fontSize: 12 }}>100%</span>
      </div>
    </div>
  );
}
