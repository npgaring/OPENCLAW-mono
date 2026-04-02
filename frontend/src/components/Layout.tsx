interface LayoutProps {
  children: React.ReactNode;
}

export function Layout({ children }: LayoutProps) {
  return (
    <main className="page">
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
