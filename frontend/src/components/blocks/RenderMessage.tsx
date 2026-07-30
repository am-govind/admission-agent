import type { ContentBlock, RenderState } from '../../types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line, AreaChart, Area,
  PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts';

function TableBlock({ block }: { block: Extract<ContentBlock, { type: 'table' }> }) {
  const { columns, rows } = block.data;
  return (
    <div className="my-3 overflow-x-auto rounded-xl border border-slate-200 shadow-sm">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-100/80">
          <tr>
            {columns.map((c) => (
              <th key={c} className="px-4 py-2.5 text-left font-semibold text-slate-700 border-b border-slate-200">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i} className={i % 2 ? 'bg-white' : 'bg-slate-50/50 hover:bg-slate-100/50 transition-colors'}>
              {r.map((cell, j) => (
                <td key={j} className="px-4 py-2 text-slate-700">
                  {String(cell).replace(/T00:00:00.*/, '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ImageBlock({ block }: { block: Extract<ContentBlock, { type: 'image' }> }) {
  return (
    <div className="my-3 overflow-hidden rounded-xl border border-slate-200 shadow-sm bg-white p-2">
      <img
        src={block.data.url}
        alt={block.data.alt ?? 'chart'}
        className="max-w-full rounded-lg mx-auto"
      />
    </div>
  );
}

function CodeBlock({ block }: { block: Extract<ContentBlock, { type: 'code' }> }) {
  return (
    <pre className="my-3 overflow-x-auto rounded-xl bg-slate-900 p-4 text-xs text-slate-100 shadow-sm">
      <code>{block.data.text}</code>
    </pre>
  );
}

const PALETTE = ['#6366f1', '#f43f5e', '#10b981', '#f59e0b', '#0ea5e9', '#a855f7', '#14b8a6', '#ef4444'];

/** Indian short scale for axis ticks: 12000000 -> "1.2 Cr". */
function compact(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e7) return `${(n / 1e7).toFixed(1)} Cr`;
  if (a >= 1e5) return `${(n / 1e5).toFixed(1)} L`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(0)}k`;
  return String(n);
}

function ChartBlock({ block }: { block: Extract<ContentBlock, { type: 'chart' }> }) {
  const { kind, x, y, title, rows } = block.data;
  const tick = { fill: '#64748b', fontSize: 11 };
  const crowded = rows.length > 6;
  const tooltip = {
    contentStyle: {
      borderRadius: 12,
      border: '1px solid #e2e8f0',
      fontSize: 12,
      boxShadow: '0 6px 16px rgba(15,23,42,.08)',
    },
    formatter: (v: unknown) =>
      typeof v === 'number' ? new Intl.NumberFormat('en-IN').format(v) : String(v),
  };

  let chart;
  if (kind === 'pie') {
    chart = (
      <PieChart>
        <Pie data={rows} dataKey={y[0]} nameKey={x} innerRadius="48%" outerRadius="78%" paddingAngle={2}>
          {rows.map((_, i) => (
            <Cell key={i} fill={PALETTE[i % PALETTE.length]} stroke="#fff" strokeWidth={2} />
          ))}
        </Pie>
        <Tooltip {...tooltip} />
        <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
      </PieChart>
    );
  } else {
    const Wrapper = kind === 'line' ? LineChart : kind === 'area' ? AreaChart : BarChart;
    const Series = kind === 'line' ? Line : Area;
    chart = (
      <Wrapper data={rows} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
        <XAxis
          dataKey={x}
          tick={tick}
          tickLine={false}
          axisLine={{ stroke: '#e2e8f0' }}
          interval="preserveStartEnd"
          angle={crowded ? -30 : 0}
          textAnchor={crowded ? 'end' : 'middle'}
          height={crowded ? 56 : 28}
        />
        <YAxis tick={tick} tickLine={false} axisLine={false} width={58} tickFormatter={(v) => compact(Number(v))} />
        <Tooltip {...tooltip} cursor={{ fill: 'rgba(99,102,241,.06)' }} />
        {y.length > 1 && <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />}
        {y.map((key, i) =>
          kind === 'bar' ? (
            <Bar key={key} dataKey={key} name={key} fill={PALETTE[i % PALETTE.length]} radius={[6, 6, 0, 0]} maxBarSize={48} />
          ) : (
            <Series
              key={key}
              type="monotone"
              dataKey={key}
              name={key}
              stroke={PALETTE[i % PALETTE.length]}
              fill={PALETTE[i % PALETTE.length]}
              fillOpacity={kind === 'area' ? 0.16 : 0}
              strokeWidth={2}
              dot={rows.length <= 12 ? { r: 3 } : false}
            />
          ),
        )}
      </Wrapper>
    );
  }

  return (
    <div className="my-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      {title && <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>}
      <ResponsiveContainer width="100%" height={280}>
        {chart}
      </ResponsiveContainer>
    </div>
  );
}

function Block({ block }: { block: ContentBlock | undefined }) {
  if (!block) return null;
  switch (block.type) {
    case 'table':
      return <TableBlock block={block} />;
    case 'chart':
      return <ChartBlock block={block} />;
    case 'image':
      return <ImageBlock block={block} />;
    case 'code':
      return <CodeBlock block={block} />;
    case 'text':
      return <p className="whitespace-pre-wrap">{block.data.text}</p>;
  }
}

export default function RenderMessage({ state }: { state: RenderState }) {
  return (
    <div className="space-y-2 text-slate-800 text-sm leading-relaxed">
      {state.parts.map((part) => {
        if (part.type === 'text') {
          const isProvenance = part.content.startsWith('How I got this:') || part.content.startsWith('Provenance:') || part.content.startsWith('*Provenance:*') || part.content.startsWith('*Data source:*');
          if (isProvenance) {
            return (
              <p
                key={part.id}
                className="mt-3 pt-2 border-t border-slate-100 text-xs italic text-slate-400"
              >
                {part.content.replace(/^\*|\*$/g, '')}
              </p>
            );
          }
          return (
            <div key={part.id} className="markdown-body space-y-2 overflow-x-auto">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  table: ({ node, ...props }) => (
                    <div className="my-3 overflow-x-auto rounded-xl border border-slate-200 shadow-sm">
                      <table className="min-w-full text-sm divide-y divide-slate-200" {...props} />
                    </div>
                  ),
                  thead: ({ node, ...props }) => <thead className="bg-slate-100/80" {...props} />,
                  tbody: ({ node, ...props }) => <tbody className="divide-y divide-slate-100 bg-white" {...props} />,
                  tr: ({ node, ...props }) => <tr className="hover:bg-slate-50/80 transition-colors" {...props} />,
                  th: ({ node, ...props }) => (
                    <th className="px-4 py-2.5 text-left font-semibold text-slate-700 border-b border-slate-200" {...props} />
                  ),
                  td: ({ node, ...props }) => <td className="px-4 py-2 text-slate-700" {...props} />,
                  p: ({ node, ...props }) => <p className="my-1.5 leading-relaxed" {...props} />,
                  ul: ({ node, ...props }) => <ul className="my-2 list-disc pl-5 space-y-1 text-slate-700" {...props} />,
                  ol: ({ node, ...props }) => <ol className="my-2 list-decimal pl-5 space-y-1 text-slate-700" {...props} />,
                  li: ({ node, ...props }) => <li className="leading-relaxed" {...props} />,
                  strong: ({ node, ...props }) => <strong className="font-semibold text-slate-900" {...props} />,
                  h1: ({ node, ...props }) => <h1 className="text-base font-bold text-slate-900 mt-4 mb-2" {...props} />,
                  h2: ({ node, ...props }) => <h2 className="text-sm font-bold text-slate-900 mt-3 mb-1.5" {...props} />,
                  h3: ({ node, ...props }) => <h3 className="text-sm font-semibold text-slate-900 mt-2.5 mb-1" {...props} />,
                  code: ({ node, ...props }) => (
                    <code className="bg-slate-100 text-rose-600 px-1.5 py-0.5 rounded text-xs font-mono" {...props} />
                  ),
                }}
              >
                {part.content}
              </ReactMarkdown>
            </div>
          );
        }
        return <Block key={part.id} block={state.contentBlocks[part.id]} />;
      })}
    </div>
  );
}
