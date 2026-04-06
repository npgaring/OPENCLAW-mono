import { Link, useLocation } from 'react-router-dom';

interface LayoutProps {
  children: React.ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const location = useLocation();

  return (
    <main className="page">
      <nav className="layout-nav">
        <Link to="/" className={`nav-link${location.pathname === '/' ? ' active' : ''}`}>Console</Link>
        <Link to="/projects" className={`nav-link${location.pathname === '/projects' ? ' active' : ''}`}>Projects</Link>
      </nav>
      <section className="hero">
        <div className="eyebrow">OpenClaw Dual Engine</div>
        <h1>Governed Builder Console</h1>
        <p>
          React + TypeScript operator console for governed v2 flow: intent, SoT lock, approval, compile, execution lock,
          and dispatch.
        </p>
      </section>
      {children}
    </main>
  );
}
