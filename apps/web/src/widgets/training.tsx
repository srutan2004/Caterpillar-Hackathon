// Training hub (§10.8): module list with progress, video player with chapters, quizzes with manual excerpts,
// instructor slots and booking. Certification status drives the gating shown at machine select.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useFormatters } from "../runtime/format";
import { useSelection } from "../runtime/selection";
import { Meter, StatusBadge, type Tier } from "./status";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

interface Chapter {
  t: number;
  title_key: string;
}

interface Lesson {
  id: string;
  kind: string;
  order: number;
  video: { uri: string; duration_s: number; chapters: Chapter[]; status: string; title_key: string } | null;
}

interface Module {
  id: string;
  title_key: string;
  machine_class: string;
  kind: string;
  est_minutes: number;
  prerequisites: string[];
  lessons: Lesson[];
  quiz_questions: number;
}

interface Cert {
  module_id: string;
  machine_class: string;
  expires_at: string;
  days_left: number;
  status: string;
}

interface Assignment {
  id: string;
  module_id: string;
  reason_kind: string;
  due_at: string | null;
  status: string;
}

interface TrainingMe {
  modules: Module[];
  progress: Record<string, { lessons: number; completed: number }>;
  certifications: Cert[];
  expiring: Cert[];
  assignments: Assignment[];
}

const CERT_TIER: Record<string, Tier> = { valid: "normal", expiring: "caution", expired: "warning", missing: "warning" };

export function TrainingHub({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const qc = useQueryClient();
  const machineId = useSelection((s) => s.machineId);
  const q = useQuery({ queryKey: ["training_me", machineId], queryFn: () => api<TrainingMe>(`/api/training/me${machineId ? `?machine=${encodeURIComponent(machineId)}` : ""}`) });
  const [openModule, setOpenModule] = useState<string | null>(null);
  const sync = useMutation({
    mutationFn: () => api<{ created: unknown[] }>("/api/training/me/sync", { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["training_me", machineId] }),
  });
  const data = q.data;
  if (!data) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t(q.isError ? "app.error_generic" : "app.loading")}</p>
      </Tile>
    );
  }
  const assigned = new Set(data.assignments.map((a) => a.module_id));
  return (
    <Tile type={widget.type}>
      {data.expiring.length ? (
        <ul className="certs small">
          {data.expiring.map((c) => (
            <li key={c.module_id}>
              <StatusBadge tier={CERT_TIER[c.status] ?? "caution"} />
              {t("training.cert_expiring", { module: t(`training.module.${c.module_id}`), days: f.num(c.days_left, 0) })}
            </li>
          ))}
        </ul>
      ) : null}
      <ul className="task-list">
        {data.modules.map((m) => {
          const p = data.progress[m.id] ?? { lessons: 0, completed: 0 };
          const assignment = data.assignments.find((a) => a.module_id === m.id);
          return (
            <li key={m.id} className="task-card" data-selected={openModule === m.id}>
              <button type="button" className="task-card-head" onClick={() => setOpenModule(openModule === m.id ? null : m.id)} aria-expanded={openModule === m.id}>
                <span className="strong">{t(m.title_key)}</span>
                <span className="muted small">{t("training.minutes", { n: m.est_minutes })}</span>
                {assigned.has(m.id) ? <span className="chip">{t(`training.reason.${assignment?.reason_kind}`, { defaultValue: t("training.assigned") })}</span> : null}
              </button>
              <Meter fraction={p.lessons ? p.completed / p.lessons : 0} tier="normal" label={t("training.progress", { done: p.completed, total: p.lessons })} />
              <p className="small muted">{t("training.progress", { done: p.completed, total: p.lessons })}</p>
              {openModule === m.id ? <ModuleDetail module={m} /> : null}
            </li>
          );
        })}
      </ul>
      <button type="button" disabled={sync.isPending} onClick={() => sync.mutate()}>
        {t("training.sync")}
      </button>
    </Tile>
  );
}

function ModuleDetail({ module }: { module: Module }) {
  const { t } = useTranslation();
  const f = useFormatters();
  const video = module.lessons.find((l) => l.video)?.video ?? null;
  const ref = useRef<HTMLVideoElement>(null);
  return (
    <div className="module-detail">
      {video ? (
        <>
          {video.status === "to_produce" ? (
            <p className="small muted">{t("training.video_pending")}</p>
          ) : (
            <video ref={ref} controls preload="metadata" src={video.uri} aria-label={t(video.title_key)} />
          )}
          <ul className="chapters small">
            {video.chapters.map((c) => (
              <li key={c.t}>
                <button type="button" onClick={() => ref.current && (ref.current.currentTime = c.t)}>
                  {t(c.title_key)}
                  <span className="sep" />
                  {f.minutes(c.t / SECONDS_PER_MINUTE)}
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {module.quiz_questions > 0 ? <Quiz moduleId={module.id} /> : <p className="small muted">{t("training.quiz_pending")}</p>}
    </div>
  );
}

interface Question {
  id: string;
  stem: string;
  options: string[];
}

interface QuizResult {
  score: number;
  passed: boolean;
  pass_mark: number;
  detail: { question_id: string; correct: boolean; answer: string | null; excerpt: { heading: string; text: string } | null }[];
}

export function Quiz({ moduleId }: { moduleId: string }) {
  const { t } = useTranslation();
  const f = useFormatters();
  const q = useQuery({ queryKey: ["quiz", moduleId], queryFn: () => api<{ questions: Question[] }>(`/api/training/modules/${encodeURIComponent(moduleId)}/quiz`) });
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const submit = useMutation({
    mutationFn: () => api<QuizResult>(`/api/training/modules/${encodeURIComponent(moduleId)}/attempts`, { method: "POST", body: JSON.stringify({ answers }) }),
  });
  if (!q.data) return <p className="small muted">{t(q.isError ? "training.quiz_pending" : "app.loading")}</p>;
  const result = submit.data;
  return (
    <div className="quiz">
      <ol className="quiz-list">
        {q.data.questions.map((question) => {
          const detail = result?.detail.find((d) => d.question_id === question.id);
          return (
            <li key={question.id} data-correct={detail ? detail.correct : undefined}>
              <p>{question.stem}</p>
              {question.options.map((opt) => (
                <label key={opt} className="small">
                  <input type="radio" name={question.id} value={opt} checked={answers[question.id] === opt} onChange={() => setAnswers((a) => ({ ...a, [question.id]: opt }))} disabled={!!result} />
                  {opt}
                </label>
              ))}
              {detail && !detail.correct ? (
                <p className="small muted">
                  {t("training.correct_answer", { answer: detail.answer ?? "" })}
                  {detail.excerpt ? (
                    <>
                      <span className="sep" />
                      {t("training.see_manual", { heading: detail.excerpt.heading })}
                    </>
                  ) : null}
                </p>
              ) : null}
            </li>
          );
        })}
      </ol>
      {result ? (
        <p className="small">
          <StatusBadge tier={result.passed ? "normal" : "caution"} />
          {t(result.passed ? "training.quiz_passed" : "training.quiz_failed", { score: f.pct(result.score), mark: f.pct(result.pass_mark) })}
        </p>
      ) : (
        <button type="button" className="primary" disabled={Object.keys(answers).length < q.data.questions.length || submit.isPending} onClick={() => submit.mutate()}>
          {t("training.submit_quiz")}
        </button>
      )}
    </div>
  );
}

interface Slot {
  id: string;
  instructor_id: string;
  mode: string;
  start: string;
  end: string;
  capacity: number;
  booked: number;
  free: number;
}

export function SlotCalendar({ widget }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const qc = useQueryClient();
  const [moduleId, setModuleId] = useState("");
  const q = useQuery({ queryKey: ["slots"], queryFn: () => api<Slot[]>("/api/training/slots") });
  const mods = useQuery({ queryKey: ["training_modules"], queryFn: () => api<Module[]>("/api/training/modules") });
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const bookIt = useMutation({
    mutationFn: (slotId: string) => api<{ id: string }>("/api/training/bookings", { method: "POST", body: JSON.stringify({ slot_id: slotId, module_id: moduleId }) }),
    onSuccess: () => {
      setErrorKey(null);
      void qc.invalidateQueries({ queryKey: ["slots"] });
    },
    onError: (err: unknown) => setErrorKey((err as { messageKey?: string })?.messageKey ?? "app.error_generic"),
  });
  if (!q.data) {
    return (
      <Tile type={widget.type}>
        <p className="muted">{t(q.isError ? "app.error_generic" : "app.loading")}</p>
      </Tile>
    );
  }
  return (
    <Tile type={widget.type}>
      <label className="small">
        {t("training.choose_module")}
        <select value={moduleId} onChange={(e) => setModuleId(e.target.value)}>
          <option value="">{t("training.choose_module")}</option>
          {(mods.data ?? []).map((m) => (
            <option key={m.id} value={m.id}>
              {t(m.title_key)}
            </option>
          ))}
        </select>
      </label>
      <ul className="service-list">
        {q.data.slice(0, SLOT_LIMIT).map((s) => (
          <li key={s.id}>
            <span>
              {f.day(s.start)}
              <span className="sep" />
              {f.time(s.start)}
              <span className="dash" />
              {f.time(s.end)}
            </span>
            <span className="chip">{t(`training.mode.${s.mode}`)}</span>
            <span className="small muted">{t("training.places", { free: s.free, capacity: s.capacity })}</span>
            <button type="button" disabled={!moduleId || s.free <= 0 || bookIt.isPending} onClick={() => bookIt.mutate(s.id)}>
              {t("training.book")}
            </button>
          </li>
        ))}
      </ul>
      {errorKey ? <p className="form-error">{t(`error.${errorKey}`, { defaultValue: t(errorKey) })}</p> : null}
      {bookIt.isSuccess ? <p className="small">{t("training.booked")}</p> : null}
    </Tile>
  );
}

/** Registry entry: a quiz pinned to one module by layout props. */
export function QuizWidget({ props }: WidgetProps) {
  return <Quiz moduleId={String(props.module_id ?? "")} />;
}

const SECONDS_PER_MINUTE = 60;
const SLOT_LIMIT = 12;
