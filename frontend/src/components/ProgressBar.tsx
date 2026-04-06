export type StepStatus = 'pending' | 'active' | 'done' | 'error';

export interface ProgressStep {
  label: string;
  status: StepStatus;
  subLabel?: string;
}

interface ProgressBarProps {
  steps: ProgressStep[];
}

function stepIcon(status: StepStatus) {
  if (status === 'done') return <span className="step-icon done">&#x2713;</span>;
  if (status === 'error') return <span className="step-icon error">&#x2717;</span>;
  if (status === 'active') return <span className="step-icon active" />;
  return <span className="step-icon pending" />;
}

export function ProgressBar({ steps }: ProgressBarProps) {
  return (
    <div className="progress-bar">
      {steps.map((step, i) => (
        <div key={i} className="progress-step-wrapper">
          {i > 0 && (
            <div className={`progress-connector ${steps[i - 1].status === 'done' ? 'filled' : ''}`} />
          )}
          <div className={`progress-step ${step.status}`}>
            {stepIcon(step.status)}
            <span className="step-label">{step.label}</span>
            {step.subLabel && <span className="step-sub-label">{step.subLabel}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
