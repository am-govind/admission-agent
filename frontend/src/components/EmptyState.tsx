import { SparkIcon } from './Icons';

export const SUGGESTED = [
  { title: 'Admissions this month', prompt: 'How many admissions this month for Pune?' },
  { title: 'Day-on-day trend', prompt: 'Show the day-on-day trend for Vijayawada Vidyapeeth' },
  { title: 'Class-wise breakdown', prompt: 'Class-wise breakdown for Bengaluru' },
  { title: 'Explain a metric', prompt: 'What does ARPU mean?' },
];

export default function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-4 py-14 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-500/25">
        <SparkIcon className="h-6 w-6" />
      </div>
      <h2 className="mt-5 text-xl font-semibold text-slate-800">
        What would you like to know?
      </h2>
      <p className="mt-1.5 text-sm text-slate-500">
        Ask about admissions, finance, retention, or ARPU across any centre or region.
      </p>

      <div className="mt-8 grid w-full gap-2.5 sm:grid-cols-2">
        {SUGGESTED.map((s) => (
          <button
            key={s.prompt}
            onClick={() => onPick(s.prompt)}
            className="group rounded-xl border border-slate-200 bg-white p-3.5 text-left transition hover:-translate-y-0.5 hover:border-indigo-300 hover:shadow-md"
          >
            <p className="text-sm font-medium text-slate-800">{s.title}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{s.prompt}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
