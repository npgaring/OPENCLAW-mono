import { useState } from 'react';
import { pretty } from '../utils/format';

interface JsonViewerProps {
  label: string;
  value: unknown;
}

export function JsonViewer({ label, value }: JsonViewerProps) {
  const [open, setOpen] = useState(false);
  const isEmpty = value === null || value === undefined || value === '';

  return (
    <div className="json-viewer">
      <button
        type="button"
        className="json-viewer-toggle"
        onClick={() => setOpen(!open)}
      >
        <span className={`json-viewer-chevron${open ? ' open' : ''}`}>&#x25B6;</span>
        <span className="json-viewer-label">{label}</span>
        {isEmpty && <span className="json-viewer-empty-tag">empty</span>}
      </button>
      {open && (
        <div className="json-box">
          <pre>{pretty(value)}</pre>
        </div>
      )}
    </div>
  );
}
