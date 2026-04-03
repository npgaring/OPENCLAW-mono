import { useMemo } from 'react';

interface PreviewPanelProps {
  files: { path: string; content: string }[];
  previewUrl: string | null;
}

function buildPreviewHtml(files: { path: string; content: string }[]): string {
  const cssFiles = files.filter((f) => f.path.endsWith('.css'));
  const pageFile = files.find((f) => f.path === 'src/app/page.tsx');
  const layoutFile = files.find((f) => f.path === 'src/app/layout.tsx');

  let cssContent = '';
  for (const f of cssFiles) {
    const cleaned = f.content
      .replace(/@import\s+"tailwindcss";\s*/, '')
      .replace(/@tailwind[^;]*;/g, '');
    cssContent += cleaned + '\n';
  }

  let bodyContent = '';
  if (pageFile) {
    bodyContent = extractJsxPreview(pageFile.content);
  }

  const projectName = extractProjectName(layoutFile?.content);

  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${projectName} - Preview</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    ${cssContent}
    body { font-family: 'Inter', system-ui, sans-serif; margin: 0; }
    a { text-decoration: none; color: inherit; }
  </style>
</head>
<body>
  ${bodyContent}
</body>
</html>`;
}

function extractJsxPreview(tsx: string): string {
  const returnMatch = tsx.match(/return\s*\(\s*([\s\S]*)\s*\);\s*\}/);
  if (!returnMatch) return '<div style="padding: 2rem; text-align: center;">Preview not available for this component.</div>';

  let jsx = returnMatch[1];
  jsx = jsx.replace(/\{`[^`]*`\}/g, '');
  jsx = jsx.replace(/\{[^{}]*\}/g, '');
  jsx = jsx.replace(/className=/g, 'class=');
  jsx = jsx.replace(/htmlFor=/g, 'for=');
  jsx = jsx.replace(/<>/g, '<div>').replace(/<\/>/g, '</div>');
  jsx = jsx.replace(/<([a-z][a-zA-Z]*)\s([^>]*)\s\/>/g, '<$1 $2></$1>');

  return jsx;
}

function extractProjectName(layoutContent?: string): string {
  if (!layoutContent) return 'Preview';
  const match = layoutContent.match(/title:\s*"([^"]+)"/);
  return match ? match[1] : 'Preview';
}

export function PreviewPanel({ files, previewUrl }: PreviewPanelProps) {
  const previewHtml = useMemo(() => {
    if (previewUrl || files.length === 0) return null;
    return buildPreviewHtml(files);
  }, [files, previewUrl]);

  if (previewUrl) {
    return (
      <div className="preview-panel">
        <div className="preview-header">
          <span>Live Preview</span>
          <a href={previewUrl} target="_blank" rel="noopener noreferrer" className="preview-link">
            Open in new tab ↗
          </a>
        </div>
        <iframe
          src={previewUrl}
          className="preview-iframe"
          title="Site preview"
          sandbox="allow-scripts allow-same-origin"
        />
      </div>
    );
  }

  if (previewHtml) {
    return (
      <div className="preview-panel">
        <div className="preview-header">
          <span>Local Preview (approximate)</span>
        </div>
        <iframe
          srcDoc={previewHtml}
          className="preview-iframe"
          title="Site preview"
          sandbox="allow-scripts"
        />
      </div>
    );
  }

  return (
    <div className="preview-panel preview-empty">
      <p>Compile an execution plan to see a preview of your site.</p>
    </div>
  );
}
