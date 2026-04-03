import { useMemo } from 'react';

interface CodeEditorProps {
  files: { path: string; content: string }[];
  selectedPath: string | null;
  onContentChange?: (path: string, content: string) => void;
}

function languageForPath(path: string): string {
  if (path.endsWith('.tsx') || path.endsWith('.ts')) return 'typescript';
  if (path.endsWith('.css')) return 'css';
  if (path.endsWith('.json')) return 'json';
  if (path.endsWith('.mjs') || path.endsWith('.js')) return 'javascript';
  if (path.endsWith('.html')) return 'html';
  return 'plaintext';
}

export function CodeEditor({ files, selectedPath, onContentChange }: CodeEditorProps) {
  const selectedFile = useMemo(
    () => files.find((f) => f.path === selectedPath),
    [files, selectedPath],
  );

  if (!selectedFile) {
    return (
      <div className="code-editor-empty">
        <p>Select a file from the tree to view its code.</p>
      </div>
    );
  }

  const lang = languageForPath(selectedFile.path);
  const lineCount = selectedFile.content.split('\n').length;

  return (
    <div className="code-editor">
      <div className="code-editor-header">
        <span className="code-editor-path">{selectedFile.path}</span>
        <span className="code-editor-lang">{lang}</span>
        <span className="code-editor-lines">{lineCount} lines</span>
      </div>
      <div className="code-editor-body">
        <div className="code-editor-gutter">
          {Array.from({ length: lineCount }, (_, i) => (
            <div key={i} className="code-editor-line-num">{i + 1}</div>
          ))}
        </div>
        <textarea
          className="code-editor-textarea"
          value={selectedFile.content}
          onChange={(e) => onContentChange?.(selectedFile.path, e.target.value)}
          spellCheck={false}
        />
      </div>
    </div>
  );
}
