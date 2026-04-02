interface StatusPillProps {
  children: React.ReactNode;
  variant?: 'default' | 'good' | 'warn' | 'bad';
}

export function StatusPill({ children, variant = 'default' }: StatusPillProps) {
  const cls = variant === 'default' ? 'pill' : `pill ${variant}`;
  return <span className={cls}>{children}</span>;
}
