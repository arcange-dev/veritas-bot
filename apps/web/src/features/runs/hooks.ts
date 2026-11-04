/**
 * Server state for runs. A run changes on the server while it executes, so the
 * detail query polls until the run is terminal and then stops; polling a
 * finished run is wasted load.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { runsApi, type StartRunInput } from "./api";
import { TERMINAL, type RunDetail, type RunStatus } from "./schemas";

export const POLL_ACTIVE_MS = 2000;
/** Waiting on a human does not need fast polling. */
export const POLL_WAITING_MS = 5000;

/** Pure so it can be tested without timers or React. */
export function pollInterval(status: RunStatus | undefined): number | false {
  if (!status) return POLL_ACTIVE_MS;          // first load: keep trying
  if (TERMINAL.has(status)) return false;
  if (status === "waiting_approval" || status === "paused") return POLL_WAITING_MS;
  return POLL_ACTIVE_MS;
}

export const runKeys = {
  all: (orgId: string) => ["runs", orgId] as const,
  detail: (orgId: string, runId: string) => ["runs", orgId, runId] as const,
};

export function useRun(orgId: string | null, runId: string | null) {
  return useQuery<RunDetail>({
    queryKey: runKeys.detail(orgId ?? "", runId ?? ""),
    queryFn: () => runsApi.detail(orgId as string, runId as string),
    enabled: Boolean(orgId && runId),
    refetchInterval: (query) => pollInterval(query.state.data?.status),
  });
}

export function useRuns(orgId: string | null) {
  return useQuery({
    queryKey: runKeys.all(orgId ?? ""),
    queryFn: () => runsApi.list(orgId as string),
    enabled: Boolean(orgId),
  });
}

export function useStartRun(orgId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: StartRunInput) => runsApi.start(orgId as string, input),
    onSuccess: () => client.invalidateQueries({ queryKey: runKeys.all(orgId ?? "") }),
  });
}

export function useRunControl(orgId: string | null, runId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (action: "cancel" | "pause" | "resume") =>
      runsApi.control(orgId as string, runId as string, action),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: runKeys.detail(orgId ?? "", runId ?? "") }),
  });
}

export function useDecideApproval(orgId: string | null, runId: string | null) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (v: { approvalId: string; approve: boolean; note?: string }) =>
      runsApi.decide(orgId as string, v.approvalId, v.approve, v.note ?? ""),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: runKeys.detail(orgId ?? "", runId ?? "") }),
  });
}
