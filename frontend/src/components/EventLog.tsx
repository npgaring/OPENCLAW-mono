import type { EventLogItem } from '../types/governed';

interface EventLogProps {
  items: EventLogItem[];
}

export function EventLog({ items }: EventLogProps) {
  return (
    <article className="panel">
      <div className="head">
        <h2>Event Log</h2>
      </div>
      <div className="body">
        <ol className="log">
          {items.map((row, i) => (
            <li key={`${row.at}-${i}`}>
              [{row.at}] {row.level.toUpperCase()}: {row.message}
            </li>
          ))}
        </ol>
      </div>
    </article>
  );
}
