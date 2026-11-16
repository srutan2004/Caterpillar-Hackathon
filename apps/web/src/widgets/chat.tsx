// Ask mode UI (§12.2): question → answer with citations, a confidence badge and a reasoning-trace panel.
// Refusals and bounded fallbacks render from their message key, so the UI never invents copy.
import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useSelection } from "../runtime/selection";
import { StatusBadge, type Tier } from "./status";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

interface Citation {
  id: string;
  kind: string;
  section?: string;
  heading?: string;
  machine_class?: string;
  score?: number;
}

interface TraceStep {
  node: string;
  [key: string]: unknown;
}

interface AskReply {
  session_id: string;
  text: string;
  message_key: string | null;
  citations: Citation[];
  confidence: string;
  confidence_score: number;
  intent: string;
  trace: TraceStep[];
  suggested_actions: { kind: string; requires_confirmation: boolean }[];
  blocked: boolean;
}

interface Turn {
  question: string;
  reply?: AskReply;
}

const CONFIDENCE_TIER: Record<string, Tier> = { high: "normal", medium: "caution", low: "warning" };

export function ChatPanel({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const machineId = useSelection((s) => s.machineId);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [openTrace, setOpenTrace] = useState<number | null>(null);
  const session = useRef<string | null>(null);

  const send = useMutation({
    mutationFn: (question: string) =>
      api<AskReply>("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message: question, session_id: session.current, machine_id: machineId, device: "mobile" }),
      }),
    onSuccess: (reply) => {
      session.current = reply.session_id;
      setTurns((prev) => prev.map((turn, i) => (i === prev.length - 1 ? { ...turn, reply } : turn)));
    },
  });

  const submit = () => {
    const q = text.trim();
    if (!q) return;
    setTurns((prev) => [...prev, { question: q }]);
    setText("");
    send.mutate(q);
  };

  return (
    <Tile type={widget.type}>
      <ol className="chat-log">
        {turns.map((turn, i) => (
          <li key={`${i}-${turn.question}`}>
            <p className="chat-question">{turn.question}</p>
            {turn.reply ? (
              <div className="chat-answer" data-blocked={turn.reply.blocked}>
                <p>{turn.reply.message_key ? t(turn.reply.message_key) : turn.reply.text}</p>
                {turn.reply.citations.length ? (
                  <>
                    <p className="small muted">{t("ask.citations")}</p>
                    <ul className="citations small">
                      {turn.reply.citations.map((c) => (
                        <li key={c.id}>
                          {c.kind === "manual"
                            ? t("ask.citation.manual", { section: t(`section.${c.section}`, { defaultValue: c.section ?? "" }), heading: c.heading ?? "" })
                            : t(`ask.citation.${c.kind}`, { id: c.id, defaultValue: c.id })}
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
                <p className="small">
                  <StatusBadge tier={CONFIDENCE_TIER[turn.reply.confidence] ?? "caution"} />
                  {t("ask.confidence.label")}
                  <span className="sep" />
                  {t(`ask.confidence.${turn.reply.confidence}`)}
                </p>
                {turn.reply.suggested_actions.map((a) => (
                  <button key={a.kind} type="button">
                    {t(`ask.action.${a.kind}`, { defaultValue: a.kind })}
                  </button>
                ))}
                <button type="button" onClick={() => setOpenTrace(openTrace === i ? null : i)} aria-expanded={openTrace === i}>
                  {t("ask.trace")}
                </button>
                {openTrace === i ? (
                  <ol className="trace small">
                    {turn.reply.trace.map((step, j) => (
                      <li key={`${step.node}-${j}`}>
                        <span className="strong">{step.node}</span>
                        <span className="sep" />
                        <span className="muted">
                          {Object.entries(step)
                            .filter(([k]) => k !== "node")
                            .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                            .join(" · ")}
                        </span>
                      </li>
                    ))}
                  </ol>
                ) : null}
              </div>
            ) : (
              <p className="muted small">{t("ask.thinking")}</p>
            )}
          </li>
        ))}
      </ol>
      <div className="row">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          aria-label={t("ask.placeholder")}
          placeholder={t("ask.placeholder")}
        />
        <button type="button" className="primary" disabled={!text.trim() || send.isPending} onClick={submit}>
          {t("ask.send")}
        </button>
      </div>
      {send.isError ? <p className="form-error">{t("app.error_generic")}</p> : null}
    </Tile>
  );
}
