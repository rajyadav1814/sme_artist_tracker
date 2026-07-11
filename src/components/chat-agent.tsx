/**
 * AI Analyst Chat Panel
 *
 * Compact collapsible panel showing the 10 suggested questions and an open
 * text input for custom questions.
 *
 * Suggested question chips call `onQuestionNavigate` (navigates to the
 * dedicated AnalystPage).  The freeform input sends inline as before.
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import type { Snapshot, Roster, NewsBriefing } from '../data/types';
import { SUGGESTED_QUESTIONS, streamAnswer, buildSystemPrompt } from '../lib/ai-utils';
import type { Message } from '../lib/ai-utils';

// ── Chat message component ────────────────────────────────────────────────────

function ChatMessage({ msg, isLatest, loading }: {
  msg:      Message;
  isLatest: boolean;
  loading:  boolean;
}) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div className={[
        'flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5',
        isUser
          ? 'bg-[var(--color-text-primary)]'
          : 'bg-[var(--color-bg-secondary)] border border-[var(--color-border-light)]',
      ].join(' ')}>
        <span className={[
          'font-[family-name:var(--font-mono)] text-[8px] font-bold',
          isUser ? 'text-[var(--color-bg-primary)]' : 'text-[var(--color-text-muted)]',
        ].join(' ')}>
          {isUser ? 'YOU' : 'AI'}
        </span>
      </div>

      <div className={[
        'max-w-[78%] rounded-sm px-3.5 py-2.5',
        isUser
          ? 'bg-[var(--color-text-primary)] text-[var(--color-bg-primary)]'
          : 'bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text-secondary)]',
      ].join(' ')}>
        {!isUser && isLatest && loading && msg.content === '' ? (
          <span className="inline-block w-2 h-3 bg-[var(--color-text-muted)] animate-pulse" />
        ) : (
          <p className="text-[15px] leading-relaxed whitespace-pre-wrap font-[family-name:var(--font-ui)]">
            {msg.content}
            {!isUser && isLatest && loading && (
              <span className="ml-0.5 inline-block w-1.5 h-3 bg-[var(--color-text-muted)] animate-pulse" />
            )}
          </p>
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export interface ChatAgentProps {
  roster:             Roster;
  snapshot:           Snapshot;
  briefing:           NewsBriefing;
  /** Called when a suggested question chip is clicked — navigates to AnalystPage */
  onQuestionNavigate: (question: string) => void;
}

export function ChatAgent({ roster, snapshot, briefing, onQuestionNavigate }: ChatAgentProps) {
  const apiKey = (import.meta.env.VITE_ANTHROPIC_API_KEY as string | undefined) ?? '';

  const [open,     setOpen]     = useState(true);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input,    setInput]    = useState('');
  const [loading,  setLoading]  = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef       = useRef<HTMLTextAreaElement>(null);

  const systemPrompt = useRef('');
  useEffect(() => {
    systemPrompt.current = buildSystemPrompt(roster, snapshot, briefing);
  }, [roster, snapshot, briefing]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Inline send — used only for the freeform text input
  const send = useCallback((question: string) => {
    const q = question.trim();
    if (!q || loading) return;

    const userMsg:      Message = { role: 'user',      content: q };
    const assistantMsg: Message = { role: 'assistant', content: '' };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setInput('');
    setLoading(true);

    let accumulated = '';

    streamAnswer(
      apiKey,
      systemPrompt.current,
      [...messages, userMsg],
      text => {
        accumulated += text;
        setMessages(prev => {
          const next = [...prev];
          next[next.length - 1] = { role: 'assistant', content: accumulated };
          return next;
        });
      },
      () => setLoading(false),
      errMsg => {
        setMessages(prev => {
          const next = [...prev];
          next[next.length - 1] = { role: 'assistant', content: `⚠ ${errMsg}` };
          return next;
        });
        setLoading(false);
      },
    );
  }, [apiKey, loading, messages]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  const hasHistory = messages.length > 0;

  return (
    <div className="border border-[var(--color-border)] rounded-sm bg-[var(--color-bg-secondary)] mb-8 anim-fade-in overflow-hidden">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div
        className="flex items-center justify-between px-5 py-3.5 cursor-pointer border-b border-[var(--color-border)] hover:bg-[var(--color-bg-card)] transition-colors duration-150"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-3">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-30" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[var(--color-text-primary)]" />
          </span>
          <span className="font-[family-name:var(--font-mono)] text-[11px] tracking-[0.3em] text-[var(--color-text-primary)] uppercase">
            AI Analyst
          </span>
          <span className="font-[family-name:var(--font-mono)] text-[11px] text-[var(--color-text-muted)]">
            · Click a question for a full-page answer · type below for quick chat
          </span>
        </div>

        <div className="flex items-center gap-4">
          {!apiKey && (
            <span className="font-[family-name:var(--font-mono)] text-[10px] text-[var(--color-text-muted)] border border-[var(--color-border)] px-2 py-0.5 rounded-sm">
              NO API KEY
            </span>
          )}
          {hasHistory && (
            <button
              onClick={e => { e.stopPropagation(); setMessages([]); }}
              className="font-[family-name:var(--font-mono)] text-[10px] tracking-widest text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] uppercase transition-colors cursor-pointer"
            >
              Clear
            </button>
          )}
          <span className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)]">
            {open ? '▲' : '▼'}
          </span>
        </div>
      </div>

      {/* ── Body ───────────────────────────────────────────────────────── */}
      {open && (
        <div>

          {!apiKey && (
            <div className="px-5 py-4 border-b border-[var(--color-border)]">
              <p className="font-[family-name:var(--font-mono)] text-[12px] text-[var(--color-text-muted)]">
                Add <code className="text-[var(--color-text-secondary)]">VITE_ANTHROPIC_API_KEY</code> to{' '}
                <code className="text-[var(--color-text-secondary)]">.env</code> and rebuild to enable the AI analyst.
              </p>
            </div>
          )}

          {/* ── Suggested questions — click opens AnalystPage ─────── */}
          <div className="px-5 pt-4 pb-3 border-b border-[var(--color-border)]">
            <p className="font-[family-name:var(--font-mono)] text-[12px] tracking-[0.25em] text-[var(--color-text-muted)] uppercase mb-3">
              Top questions — click for a dedicated full-page answer ↗
            </p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTED_QUESTIONS.map((q, i) => (
                <button
                  key={i}
                  onClick={() => onQuestionNavigate(q.text)}
                  disabled={!apiKey}
                  className={[
                    'flex items-start gap-2.5 text-left px-3.5 py-2.5 rounded-sm border-2 transition-all duration-150 cursor-pointer',
                    'font-[family-name:var(--font-ui)] text-[14px] leading-snug font-bold',
                    !apiKey
                      ? 'opacity-40 cursor-not-allowed'
                      : 'hover:bg-[var(--color-bg-card)]',
                  ].join(' ')}
                  style={{
                    borderColor: `${q.color}55`,
                    color:       `${q.color}cc`,
                  }}
                  onMouseEnter={e => {
                    if (apiKey) {
                      (e.currentTarget as HTMLButtonElement).style.borderColor = q.color;
                      (e.currentTarget as HTMLButtonElement).style.color = q.color;
                      (e.currentTarget as HTMLButtonElement).style.background = `${q.color}12`;
                    }
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLButtonElement).style.borderColor = `${q.color}55`;
                    (e.currentTarget as HTMLButtonElement).style.color = `${q.color}cc`;
                    (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
                  }}
                >
                  <span
                    className="flex-shrink-0 font-[family-name:var(--font-mono)] text-[13px] font-black mt-0.5 w-5"
                    style={{ color: q.color }}
                  >
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span>{q.text}</span>
                </button>
              ))}
            </div>
          </div>

          {/* ── Inline chat history (freeform only) ───────────────── */}
          {hasHistory && (
            <div className="px-5 py-4 flex flex-col gap-4 max-h-[400px] overflow-y-auto border-b border-[var(--color-border)]">
              {messages.map((msg, i) => (
                <ChatMessage
                  key={i}
                  msg={msg}
                  isLatest={i === messages.length - 1}
                  loading={loading}
                />
              ))}
              <div ref={messagesEndRef} />
            </div>
          )}

          {/* ── Freeform input ─────────────────────────────────────── */}
          <div className="px-5 py-3.5 flex gap-3 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading || !apiKey}
              placeholder={apiKey ? 'Type a custom question for a quick inline answer… (Enter to send)' : 'API key required'}
              rows={1}
              className={[
                'flex-1 resize-none bg-[var(--color-bg-card)] border border-[var(--color-border)]',
                'rounded-sm px-3.5 py-2.5 font-[family-name:var(--font-ui)] text-[15px]',
                'text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)]',
                'focus:outline-none focus:border-[var(--color-border-light)]',
                'transition-colors duration-150 leading-relaxed',
                (!apiKey || loading) ? 'opacity-50 cursor-not-allowed' : '',
              ].join(' ')}
              style={{ minHeight: '42px', maxHeight: '120px' }}
              onInput={e => {
                const el = e.currentTarget;
                el.style.height = 'auto';
                el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
              }}
            />
            <button
              onClick={() => send(input)}
              disabled={loading || !input.trim() || !apiKey}
              className={[
                'flex-shrink-0 flex items-center gap-2 px-4 py-2.5 rounded-sm border',
                'font-[family-name:var(--font-mono)] text-[11px] tracking-widest uppercase',
                'transition-all duration-150 cursor-pointer',
                loading || !input.trim() || !apiKey
                  ? 'border-[var(--color-border)] text-[var(--color-text-muted)] opacity-50 cursor-not-allowed'
                  : 'border-[var(--color-text-primary)] bg-[var(--color-text-primary)] text-[var(--color-bg-primary)] hover:opacity-90',
              ].join(' ')}
            >
              {loading
                ? <><span className="w-2 h-2 rounded-full bg-current animate-pulse" /> Wait</>
                : <>Send ↵</>
              }
            </button>
          </div>

        </div>
      )}
    </div>
  );
}
