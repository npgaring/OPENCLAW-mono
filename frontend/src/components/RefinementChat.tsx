import { useState } from 'react';

interface RefinementChatProps {
  disabled: boolean;
  onRefine: (message: string) => void;
  history: { role: 'user' | 'system'; text: string }[];
}

export function RefinementChat({ disabled, onRefine, history }: RefinementChatProps) {
  const [input, setInput] = useState('');

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed) return;
    onRefine(trimmed);
    setInput('');
  }

  return (
    <div className="refinement-chat">
      <div className="refinement-header">
        <span>Refine Your Site</span>
      </div>
      <div className="refinement-messages">
        {history.length === 0 && (
          <div className="refinement-empty">
            <p>Describe changes you&apos;d like to make to your site. Examples:</p>
            <ul>
              <li>&quot;Make the hero section more bold and use darker colors&quot;</li>
              <li>&quot;Add a testimonials section to the home page&quot;</li>
              <li>&quot;Change the CTA text to Schedule a Demo&quot;</li>
            </ul>
          </div>
        )}
        {history.map((msg, i) => (
          <div key={i} className={`refinement-msg refinement-msg-${msg.role}`}>
            <span className="refinement-role">{msg.role === 'user' ? 'You' : 'System'}</span>
            <p>{msg.text}</p>
          </div>
        ))}
      </div>
      <form className="refinement-input" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Describe a change..."
          disabled={disabled}
        />
        <button type="submit" disabled={disabled || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
