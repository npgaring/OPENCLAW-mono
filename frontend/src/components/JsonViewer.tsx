import { pretty } from '../utils/format';

interface JsonViewerProps {
  label: string;
  value: unknown;
}

export function JsonViewer({ label, value }: JsonViewerProps) {
  return (
    <div>
      <label>{label}</label>
      <div className="json-box">
        <pre>{pretty(value)}</pre>
      </div>
    </div>
  );
}
