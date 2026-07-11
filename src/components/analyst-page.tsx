/**
 * Analyst Answer Page
 *
 * A full-screen dedicated page that:
 *  - Shows the selected question in large bold type at the top
 *  - Streams the AI answer in large, comfortable reading type
 *  - Pins a scrollable question tray at the bottom so the user can
 *    jump directly to any other question without leaving the page
 *  - Displays the effective snapshot date top-right
 */

import { useState, useEffect, useRef } from 'react';
import { SUGGESTED_QUESTIONS, streamAnswer } from '../lib/ai-utils';
import type { Message } from '../lib/ai-utils';

// ── Simple markdown-to-JSX renderer ──────────────────────────────────────────
// Handles **bold**, bullet lines (- / •), and numbered lines.

function RenderAnswer({ text }: { text: string }) {
  if (!text) return null;

  const lines = text.split('\n');

  return (
    <div className="space-y-3">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={i} className="h-2" />;

        // Numbered list item: "1. ..." or "1) ..."
        const numMatch = trimmed.match(/^(\d+)[.)]\s+(.+)/);
        if (numMatch) {
          return (
            <div key={i} className="flex gap-3 items-start">
              <span
                className="flex-shrink-0 font-[family-name:var(--font-mono)] text-[16px] font-bold w-7 text-right"
                style={{ color: '#60a5fa' }}
              >
                {numMatch[1]}.
              </span>
              <p className="text-[18px] leading-relaxed text-[var(--color-text-secondary)] flex-1">
                <InlineFormatted text={numMatch[2]} />
              </p>
            </div>
          );
        }

        // Bullet list item: "- ..." or "• ..."
        const bulletMatch = trimmed.match(/^[-•*]\s+(.+)/);
        if (bulletMatch) {
          return (
            <div key={i} className="flex gap-3 items-start">
              <span className="flex-shrink-0 text-[18px] mt-0.5" style={{ color: '#fbbf24' }}>▪</span>
              <p className="text-[18px] leading-relaxed text-[var(--color-text-secondary)] flex-1">
                <InlineFormatted text={bulletMatch[1]} />
              </p>
            </div>
          );
        }

        // Section heading: line ending with ":" and no trailing text after colon (or all caps short)
        if (trimmed.endsWith(':') && trimmed.length < 60) {
          return (
            <p
              key={i}
              className="font-[family-name:var(--font-mono)] text-[14px] tracking-widest uppercase mt-4 mb-1"
              style={{ color: '#a78bfa' }}
            >
              {trimmed.slice(0, -1)}
            </p>
          );
        }

        // Regular paragraph
        return (
          <p key={i} className="text-[18px] leading-relaxed text-[var(--color-text-secondary)]">
            <InlineFormatted text={trimmed} />
          </p>
        );
      })}
    </div>
  );
}

// Handles **bold** inline spans
function InlineFormatted({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return (
            <strong key={i} className="text-[var(--color-text-primary)] font-bold">
              {part.slice(2, -2)}
            </strong>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export interface AnalystPageProps {
  question:     string;          // currently selected question
  systemPrompt: string;          // pre-built AI context
  snapshotDate: string;          // shown top-right as effective date
  apiKey:       string;
  onSelectQuestion: (q: string) => void;
}

export function AnalystPage({
  question,
  systemPrompt,
  snapshotDate,
  apiKey,
  onSelectQuestion,
}: AnalystPageProps) {
  const [answer,  setAnswer]  = useState('');
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');

  const answerRef    = useRef<HTMLDivElement>(null);
  const abortRef     = useRef<boolean>(false);

  // Stream a new answer whenever the question changes
  useEffect(() => {
    if (!question || !apiKey) return;

    abortRef.current = true;   // signal any in-flight stream to stop
    setAnswer('');
    setError('');
    setLoading(true);

    // Small tick so the abort flag propagates before we reset it
    const tid = setTimeout(() => {
      abortRef.current = false;
      let accumulated = '';

      const messages: Message[] = [{ role: 'user', content: question }];

      streamAnswer(
        apiKey,
        systemPrompt,
        messages,
        /* onChunk */ text => {
          if (abortRef.current) return;
          accumulated += text;
          setAnswer(accumulated);
        },
        /* onDone */ () => {
          if (!abortRef.current) setLoading(false);
        },
        /* onError */ msg => {
          if (!abortRef.current) {
            setError(msg);
            setLoading(false);
          }
        },
      );
    }, 50);

    return () => {
      clearTimeout(tid);
      abortRef.current = true;
    };
  }, [question, apiKey, systemPrompt]);

  // Scroll answer area to top when question changes
  useEffect(() => {
    answerRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [question]);

  const selectedIndex = SUGGESTED_QUESTIONS.findIndex(q => q.text === question);

  if (!question) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[40vh] gap-4">
        <p className="font-[family-name:var(--font-mono)] text-[16px] text-[var(--color-text-muted)] tracking-widest uppercase">
          No question selected
        </p>
        <p className="text-[15px] text-[var(--color-text-muted)] text-center max-w-sm">
          Click any question in the AI Analyst panel to see a full answer here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col" style={{ minHeight: 'calc(100vh - 200px)' }}>

      {/* ── Page header ──────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-6 mb-8">

        {/* Effective date — top right */}
        <div className="flex-shrink-0 text-right ml-auto">
          <p className="font-[family-name:var(--font-mono)] text-[12px] tracking-[0.2em] text-[var(--color-text-muted)] uppercase">
            Data valid for
          </p>
          <p
            className="font-[family-name:var(--font-mono)] text-[18px] font-bold"
            style={{ color: '#fbbf24' }}
          >
            {snapshotDate}
          </p>
        </div>
      </div>

      {/* ── Question display ─────────────────────────────────────────── */}
      <div
        className="mb-8 pb-8 border-b-2"
        style={{ borderColor: selectedIndex >= 0 ? `${SUGGESTED_QUESTIONS[selectedIndex].color}66` : '#333' }}
      >
        <p
          className="font-[family-name:var(--font-mono)] text-[12px] tracking-[0.3em] text-[var(--color-text-muted)] uppercase mb-4"
        >
          AI Analyst · Question {selectedIndex >= 0 ? String(selectedIndex + 1).padStart(2, '0') : '—'} of {SUGGESTED_QUESTIONS.length}
        </p>
        <h1
          className="font-[family-name:var(--font-headline)] font-black leading-tight text-[var(--color-text-primary)]"
          style={{
            fontSize: 'clamp(1.6rem, 3.5vw, 2.8rem)',
            color: selectedIndex >= 0 ? SUGGESTED_QUESTIONS[selectedIndex].color : '#ffffff',
          }}
        >
          {question}
        </h1>
      </div>

      {/* ── Answer area ──────────────────────────────────────────────── */}
      <div
        ref={answerRef}
        className="flex-1 overflow-y-auto pb-8"
        style={{ maxHeight: 'calc(100vh - 440px)', minHeight: '300px' }}
      >
        {loading && !answer && (
          <div className="flex items-center gap-3">
            <span className="w-2.5 h-2.5 rounded-full bg-[var(--color-text-primary)] animate-ping" />
            <span className="font-[family-name:var(--font-mono)] text-[15px] text-[var(--color-text-muted)] tracking-widest">
              Analysing data…
            </span>
          </div>
        )}

        {error && (
          <p className="text-[18px]" style={{ color: '#f87171' }}>⚠ {error}</p>
        )}

        {answer && (
          <div>
            <RenderAnswer text={answer} />
            {loading && (
              <span className="inline-block w-2 h-5 ml-1 bg-[var(--color-text-muted)] animate-pulse align-middle" />
            )}
          </div>
        )}
      </div>

      {/* ── Bottom question tray ─────────────────────────────────────── */}
      <div
        className="sticky bottom-0 left-0 right-0 mt-8 pt-4 border-t-2 border-[var(--color-border)]"
        style={{ background: 'var(--color-bg-primary)' }}
      >
        <p className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.3em] text-[var(--color-text-muted)] uppercase mb-3">
          Other questions — click to switch
        </p>
        <div className="flex gap-2 overflow-x-auto pb-4" style={{ scrollbarWidth: 'thin' }}>
          {SUGGESTED_QUESTIONS.map((q, i) => {
            const isActive = q.text === question;
            return (
              <button
                key={i}
                onClick={() => onSelectQuestion(q.text)}
                disabled={loading}
                className={[
                  'flex-shrink-0 flex items-start gap-2 text-left px-3.5 py-2.5 rounded-sm border-2',
                  'transition-all duration-150 cursor-pointer max-w-[200px]',
                  'font-[family-name:var(--font-ui)] text-[13px] font-bold leading-snug',
                  loading ? 'opacity-50 cursor-not-allowed' : '',
                ].join(' ')}
                style={{
                  borderColor: isActive ? q.color : `${q.color}44`,
                  background:  isActive ? `${q.color}18` : 'transparent',
                  color:       isActive ? q.color : `${q.color}99`,
                  boxShadow:   isActive ? `0 0 10px ${q.color}22` : 'none',
                }}
              >
                <span
                  className="flex-shrink-0 font-[family-name:var(--font-mono)] text-[13px] font-black"
                  style={{ color: q.color }}
                >
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span className="line-clamp-2">{q.text}</span>
              </button>
            );
          })}
        </div>
      </div>

    </div>
  );
}
