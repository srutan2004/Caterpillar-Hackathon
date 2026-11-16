// Incident list, black-box playback and supervisor workflow (§10.4.8). The replay reuses the twin side view.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { routes } from "../api/routes";
import { useBootstrap } from "../app/bootstrap";
import { resourceKey } from "../runtime/binding";
import { useFormatters } from "../runtime/format";
import { useSelection } from "../runtime/selection";
import { secondsToMs } from "../runtime/time";
import { TwinView } from "./live";
import { StatusBadge, type Tier } from "./status";
import { Tile } from "./Tile";
import type { WidgetProps } from "./types";

interface Incident {
  id: string;
  machine_id: string | null;
  kind: string;
  severity: string;
  source: string;
  occurred_at: string;
  description: string | null;
  status: string;
  blackbox_clip_id: string | null;
}

interface Playback {
  incident: Incident;
  clip: { pre_s: number; post_s: number; t0: string } | null;
  frames: Record<string, unknown>[];
  markers: { ts: string; rule_id: string; severity: string }[];
  workflow: string[];
}

const SEVERITY_TIER: Record<string, Tier> = { low: "advisory", medium: "caution", high: "warning" };
const NO_INCIDENTS: Incident[] = [];
const REVIEW_ROLES = ["supervisor", "admin"];

export function IncidentPlayback({ widget, binding }: WidgetProps) {
  const { t } = useTranslation();
  const f = useFormatters();
  const boot = useBootstrap();
  const qc = useQueryClient();
  const incidents = (binding.value as Incident[] | undefined) ?? NO_INCIDENTS;
  const selected = useSelection((s) => s.incidentId);
  const select = useSelection((s) => s.select);
  useEffect(() => {
    if (incidents.length && (!selected || !incidents.some((i) => i.id === selected))) select({ incidentId: incidents[0].id });
  }, [incidents, selected, select]);
  const q = useQuery({ queryKey: ["playback", selected], queryFn: () => api<Playback>(routes.playback(selected as string)), enabled: !!selected });
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const frames = q.data?.frames ?? [];
  useEffect(() => setIdx(0), [selected]);
  const frameMs = frames.length > 1 ? new Date(String(frames[1].ts)).getTime() - new Date(String(frames[0].ts)).getTime() : secondsToMs(1);
  useEffect(() => {
    if (!playing || !frames.length) return undefined;
    const id = setInterval(() => setIdx((i) => (i + 1 < frames.length ? i + 1 : i)), frameMs);
    return () => clearInterval(id);
  }, [playing, frames.length, frameMs]);
  const advance = useMutation({
    mutationFn: (status: string) => api(routes.incident(selected as string), { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: resourceKey("incidents") });
      void qc.invalidateQueries({ queryKey: ["playback", selected] });
    },
  });
  const canReview = REVIEW_ROLES.includes(boot?.user?.role ?? "");
  const inc = q.data?.incident;
  const wf = q.data?.workflow ?? [];
  const next = inc && wf.indexOf(inc.status) >= 0 ? wf[wf.indexOf(inc.status) + 1] : undefined;
  const frame = frames[Math.min(idx, frames.length - 1)];
  const t0 = frames.length ? new Date(String(frames[0].ts)).getTime() : 0;
  const t1 = frames.length ? new Date(String(frames[frames.length - 1].ts)).getTime() : 1;
  const tracks = (frame?.tracks as { track_id: string; distance_m: number }[] | undefined) ?? [];
  return (
    <Tile type={widget.type}>
      <div className="incident-layout">
        <ul className="incident-list">
          {incidents.length === 0 ? <li className="muted">{t("widget.incident_playback.none")}</li> : null}
          {incidents.map((i) => (
            <li key={i.id} data-selected={i.id === selected}>
              <button type="button" onClick={() => select({ incidentId: i.id })} aria-pressed={i.id === selected}>
                <StatusBadge tier={SEVERITY_TIER[i.severity] ?? "advisory"} />
                <span className="strong">{t(`incident.kind.${i.kind}`)}</span>
                <span className="small muted">
                  {f.day(i.occurred_at)}
                  <span className="sep" />
                  {f.time(i.occurred_at)}
                  <span className="sep" />
                  {i.machine_id ?? "—"}
                </span>
                <span className="chip">{t(`workflow.incident.${i.status}`)}</span>
                <span className="chip">{t(`incident.source.${i.source}`)}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="incident-detail">
          {inc ? (
            <>
              <p className="small">{inc.description ? t(`incident.description.${inc.description}`, { defaultValue: inc.description }) : null}</p>
              {frames.length && frame ? (
                <>
                  <TwinView state={frame} tier={tracks.length ? "caution" : "normal"} />
                  <div className="scrubber">
                    <button type="button" onClick={() => setPlaying((p) => !p)} aria-pressed={playing}>
                      {t(playing ? "widget.incident_playback.pause" : "widget.incident_playback.play")}
                    </button>
                    <input
                      type="range"
                      min={0}
                      max={frames.length - 1}
                      value={idx}
                      onChange={(e) => setIdx(Number(e.target.value))}
                      aria-label={t("widget.incident_playback.scrub")}
                    />
                    <span className="small">{f.time(String(frame.ts))}</span>
                  </div>
                  <ol className="marker-track" aria-label={t("widget.incident_playback.markers")}>
                    {(q.data?.markers ?? []).map((m) => {
                      const x = (new Date(m.ts).getTime() - t0) / (t1 - t0 || 1);
                      return (
                        <li key={`${m.rule_id}-${m.ts}`} style={{ left: `${Math.max(0, Math.min(1, x)) * PERCENT_100}%` }} data-tier={m.severity}>
                          <button
                            type="button"
                            onClick={() => setIdx(Math.round(Math.max(0, Math.min(1, x)) * (frames.length - 1)))}
                            title={t(`rule.${m.rule_id}`, { defaultValue: m.rule_id })}
                          >
                            <StatusBadge tier={m.severity as Tier} />
                          </button>
                        </li>
                      );
                    })}
                  </ol>
                  <p className="small muted">
                    {t("widget.incident_playback.people", { n: tracks.length })}
                    {tracks.length ? (
                      <>
                        <span className="sep" />
                        {t("widget.incident_playback.nearest", { d: f.num(Math.min(...tracks.map((x) => x.distance_m))) })}
                      </>
                    ) : null}
                  </p>
                </>
              ) : (
                <p className="muted">{t("widget.incident_playback.no_clip")}</p>
              )}
              {canReview && next ? (
                <button type="button" className="primary" disabled={advance.isPending} onClick={() => advance.mutate(next)}>
                  {t("widget.incident_playback.advance", { status: t(`workflow.incident.${next}`) })}
                </button>
              ) : null}
            </>
          ) : (
            <p className="muted">{t(q.isLoading ? "app.loading" : "app.empty")}</p>
          )}
        </div>
      </div>
    </Tile>
  );
}

const PERCENT_100 = 100;
