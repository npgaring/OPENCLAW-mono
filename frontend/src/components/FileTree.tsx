import { useMemo } from 'react';

interface FileNode {
  name: string;
  path: string;
  children?: FileNode[];
}

interface FileTreeProps {
  files: { path: string; content: string }[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
}

function buildTree(paths: string[]): FileNode[] {
  const root: FileNode[] = [];

  for (const path of paths.sort()) {
    const parts = path.split('/');
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const name = parts[i];
      const fullPath = parts.slice(0, i + 1).join('/');
      const isFile = i === parts.length - 1;

      let existing = current.find((n) => n.name === name);
      if (!existing) {
        existing = { name, path: fullPath, children: isFile ? undefined : [] };
        current.push(existing);
      }
      if (!isFile && existing.children) {
        current = existing.children;
      }
    }
  }

  return root;
}

function iconForFile(name: string): string {
  if (name.endsWith('.tsx') || name.endsWith('.ts')) return '📄';
  if (name.endsWith('.css')) return '🎨';
  if (name.endsWith('.json')) return '⚙️';
  if (name.endsWith('.mjs') || name.endsWith('.js')) return '📦';
  if (name.startsWith('.')) return '🔧';
  return '📄';
}

function TreeNode({ node, depth, selectedPath, onSelect }: { node: FileNode; depth: number; selectedPath: string | null; onSelect: (p: string) => void }) {
  const isDir = !!node.children;
  const isSelected = node.path === selectedPath;

  return (
    <>
      <div
        className={`file-tree-item${isSelected ? ' selected' : ''}`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => !isDir && onSelect(node.path)}
      >
        <span className="file-tree-icon">{isDir ? '📁' : iconForFile(node.name)}</span>
        <span className="file-tree-name">{node.name}</span>
      </div>
      {isDir && node.children?.map((child) => (
        <TreeNode key={child.path} node={child} depth={depth + 1} selectedPath={selectedPath} onSelect={onSelect} />
      ))}
    </>
  );
}

export function FileTree({ files, selectedPath, onSelect }: FileTreeProps) {
  const tree = useMemo(() => buildTree(files.map((f) => f.path)), [files]);

  return (
    <div className="file-tree">
      <div className="file-tree-header">
        <span>Files ({files.length})</span>
      </div>
      <div className="file-tree-list">
        {tree.map((node) => (
          <TreeNode key={node.path} node={node} depth={0} selectedPath={selectedPath} onSelect={onSelect} />
        ))}
      </div>
    </div>
  );
}
